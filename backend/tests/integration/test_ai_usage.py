import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_pricing import MODEL_PRICES, ModelPrice
from app.core.pagination import encode_cursor
from app.features.ai_usage import (
    BudgetExceededError,
    UnknownModelPriceError,
    has_budget,
    metered_call,
)
from app.features.ai_usage.models import AiBudget, AiUsageEvent
from app.features.audit.models import AuditEvent

SUMMARY = "/api/v1/ai-usage/summary"
EVENTS = "/api/v1/ai-usage/events"
BUDGET = "/api/v1/ai-usage/budget"
MODEL = "text-embedding-3-small"


async def _set_limit(session: AsyncSession, limit: str) -> None:
    async with session.begin():
        await session.execute(delete(AiBudget))
        session.add(AiBudget(limit_usd=Decimal(limit)))


async def _events(session: AsyncSession) -> list[AiUsageEvent]:
    async with session.begin():
        result = await session.execute(select(AiUsageEvent).order_by(AiUsageEvent.created_at))
        return list(result.scalars())


class _BilledButUnusableError(Exception):
    billed_tokens = 500_000


async def _call(
    session: AsyncSession,
    tokens: int = 10,
    *,
    model: str = MODEL,
    output_tokens: int = 0,
    fail: Exception | None = None,
) -> int:
    """One metered call that 'bills' `tokens`; returns how often the provider ran (0 or 1)."""
    calls = 0

    async def provider_call() -> int:
        nonlocal calls
        calls += 1
        if fail is not None:
            raise fail
        return tokens

    await metered_call(
        session,
        provider="openai",
        model=model,
        operation="candidate_embedding",
        trigger="cli",
        item_count=3,
        call=provider_call,
        tokens_of=lambda billed: (billed, output_tokens),
    )
    return calls


# --- Metering ----------------------------------------------------------------------------


async def test_fresh_database_defaults_to_five_dollars(recruiter_client: AsyncClient) -> None:
    # The suite truncates the migration's seed row, so this exercises the fallback path.
    body = (await recruiter_client.get(SUMMARY)).json()

    assert Decimal(body["limit_usd"]) == Decimal("5.00")
    assert Decimal(body["spent_usd"]) == 0
    assert Decimal(body["remaining_usd"]) == Decimal("5.00")
    assert body["limit_reached"] is False


async def test_a_call_records_its_actual_cost(db_session: AsyncSession) -> None:
    await _set_limit(db_session, "5.00")

    await _call(db_session, tokens=2_500_000)

    [event] = await _events(db_session)
    assert event.status == "succeeded"
    assert event.cost_usd == Decimal("0.050000")
    assert event.input_tokens == 2_500_000
    assert (event.provider, event.model, event.trigger, event.item_count) == (
        "openai",
        MODEL,
        "cli",
        3,
    )


async def test_output_tokens_are_recorded_and_priced(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(MODEL_PRICES, "test-chat-model", ModelPrice(Decimal("0.25"), Decimal("2")))
    await _set_limit(db_session, "5.00")

    await _call(db_session, tokens=1_000_000, output_tokens=1_000_000, model="test-chat-model")

    [event] = await _events(db_session)
    assert (event.input_tokens, event.output_tokens) == (1_000_000, 1_000_000)
    assert event.cost_usd == Decimal("2.250000")


async def test_a_failed_call_is_recorded_at_zero_and_reraised(db_session: AsyncSession) -> None:
    await _set_limit(db_session, "5.00")

    with pytest.raises(RuntimeError):
        await _call(db_session, fail=RuntimeError("boom with secret text"))

    [event] = await _events(db_session)
    assert (event.status, event.cost_usd, event.error) == ("failed", Decimal(0), "RuntimeError")


async def test_a_billed_but_unusable_response_counts_as_spent(db_session: AsyncSession) -> None:
    await _set_limit(db_session, "5.00")

    with pytest.raises(_BilledButUnusableError):
        await _call(db_session, fail=_BilledButUnusableError())

    [event] = await _events(db_session)
    assert (event.status, event.input_tokens, event.cost_usd) == (
        "failed",
        500_000,
        Decimal("0.010000"),
    )


async def test_zero_limit_blocks_and_never_calls_the_provider(db_session: AsyncSession) -> None:
    await _set_limit(db_session, "0.00")

    with pytest.raises(BudgetExceededError):
        await _call(db_session)

    [event] = await _events(db_session)
    assert (event.status, event.cost_usd) == ("blocked", Decimal(0))


async def test_calls_run_while_spend_is_below_the_limit_and_stop_once_it_is_reached(
    db_session: AsyncSession,
) -> None:
    await _set_limit(db_session, "0.02")

    assert await _call(db_session, tokens=1_000_000) == 1  # spends exactly 0.02

    with pytest.raises(BudgetExceededError):
        await _call(db_session, tokens=1)
    assert await has_budget(db_session) is False


async def test_one_call_may_overshoot_the_limit_then_everything_is_refused(
    db_session: AsyncSession,
) -> None:
    """The documented shortcut: no reservation, so the last call can go over by its own cost."""
    await _set_limit(db_session, "0.01")

    await _call(db_session, tokens=1_000_000)  # 0.02 against a 0.01 limit

    with pytest.raises(BudgetExceededError):
        await _call(db_session)
    statuses = [event.status for event in await _events(db_session)]
    assert statuses == ["succeeded", "blocked"]


async def test_unknown_model_is_blocked_and_logged(db_session: AsyncSession) -> None:
    await _set_limit(db_session, "5.00")

    with pytest.raises(UnknownModelPriceError):
        await _call(db_session, model="mystery-model")

    [event] = await _events(db_session)
    assert (event.status, event.model) == ("blocked", "mystery-model")


async def test_has_budget_follows_the_spend(db_session: AsyncSession) -> None:
    await _set_limit(db_session, "0.02")
    assert await has_budget(db_session) is True

    await _call(db_session, tokens=1_000_000)

    assert await has_budget(db_session) is False


# --- API ---------------------------------------------------------------------------------


async def test_anonymous_gets_401(client: AsyncClient) -> None:
    assert (await client.get(SUMMARY)).status_code == 401
    assert (await client.get(EVENTS)).status_code == 401


async def test_recruiter_can_read_but_not_change_the_limit(
    recruiter_client: AsyncClient,
) -> None:
    assert (await recruiter_client.get(SUMMARY)).status_code == 200
    assert (await recruiter_client.get(EVENTS)).status_code == 200

    response = await recruiter_client.put(BUDGET, json={"limit_usd": "9.00"})

    assert response.status_code == 403


async def test_put_requires_the_csrf_header(admin_client: AsyncClient) -> None:
    del admin_client.headers["X-Requested-With"]

    response = await admin_client.put(BUDGET, json={"limit_usd": "9.00"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_admin_put_updates_limit_and_writes_audit_row(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.put(BUDGET, json={"limit_usd": "12.50"})

    assert response.status_code == 200
    assert Decimal(response.json()["limit_usd"]) == Decimal("12.50")
    assert Decimal((await admin_client.get(SUMMARY)).json()["limit_usd"]) == Decimal("12.50")
    async with db_session.begin():
        audit = (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "ai_budget.update")
            )
        ).scalar_one()
    assert audit.details == {"old_limit_usd": "5.00", "new_limit_usd": "12.50"}
    assert audit.actor_user_id is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"limit_usd": "-1"},
        {"limit_usd": "10001"},
        {"limit_usd": "1.234"},
        {},
        {"limit_usd": "5", "x": 1},
    ],
)
async def test_put_rejects_invalid_payloads(
    admin_client: AsyncClient, payload: dict[str, str]
) -> None:
    assert (await admin_client.put(BUDGET, json=payload)).status_code == 422


async def test_summary_totals_match_spend_and_the_limit_flag(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _set_limit(db_session, "0.05")
    await _call(db_session, tokens=1_000_000)  # 0.02
    with pytest.raises(RuntimeError):
        await _call(db_session, fail=RuntimeError("x"))  # free

    body = (await admin_client.get(SUMMARY)).json()

    assert Decimal(body["spent_usd"]) == Decimal("0.02")
    assert Decimal(body["remaining_usd"]) == Decimal("0.03")
    assert body["percent_used"] == pytest.approx(40.0)
    assert body["limit_reached"] is False
    [model_row] = body["by_model"]
    assert model_row["key"] == MODEL
    assert model_row["requests"] == 1
    assert Decimal(model_row["cost_usd"]) == Decimal(body["spent_usd"])
    assert body["by_operation"][0]["key"] == "candidate_embedding"

    await admin_client.put(BUDGET, json={"limit_usd": "0.02"})
    assert (await admin_client.get(SUMMARY)).json()["limit_reached"] is True


async def test_events_are_newest_first_filterable_and_paginated(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _set_limit(db_session, "5.00")
    for _ in range(3):
        await _call(db_session)
    with pytest.raises(RuntimeError):
        await _call(db_session, fail=RuntimeError("x"))

    first = (await admin_client.get(EVENTS, params={"limit": 3})).json()
    second = (
        await admin_client.get(EVENTS, params={"limit": 3, "cursor": first["next_cursor"]})
    ).json()
    failed = (await admin_client.get(EVENTS, params={"status": "failed"})).json()
    other_model = (await admin_client.get(EVENTS, params={"model": "nope"})).json()

    assert first["items"][0]["status"] == "failed"
    assert len(first["items"]) == 3
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    ids = [e["id"] for e in first["items"] + second["items"]]
    assert len(set(ids)) == 4
    assert len(failed["items"]) == 1
    assert other_model["items"] == []
    assert "text" not in first["items"][0]


async def test_page_size_is_capped(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(EVENTS, params={"limit": 101})).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"key": "not-a-date", "id": "x"},
        {"key": "2026-10-29T10:00:00", "id": str(uuid.uuid4())},  # naive datetime
        {"key": "0001-01-01T00:00:00+00:00", "id": str(uuid.uuid4())},
        {"key": "2026-10-29T10:00:00+00:00", "id": "not-a-uuid"},
    ],
)
async def test_tampered_cursor_is_a_400(admin_client: AsyncClient, payload: dict[str, str]) -> None:
    response = await admin_client.get(EVENTS, params={"cursor": encode_cursor(payload)})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_garbage_cursor_is_a_400(admin_client: AsyncClient) -> None:
    response = await admin_client.get(EVENTS, params={"cursor": "!!!"})

    assert response.status_code == 400
