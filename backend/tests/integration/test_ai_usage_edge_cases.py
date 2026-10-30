"""QA probes for the AI budget cap: cap edges, API validation, privacy and re-drive."""

import asyncio
import logging
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.embeddings import OpenAIEmbeddingProvider, PermanentEmbeddingError
from app.features.ai_usage import BudgetExceededError, metered_call, repository
from app.features.ai_usage.models import AiBudget, AiUsageEvent
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import CANDIDATES, EmbedOutcome, embed_stale
from app.features.embeddings.models import EmbeddingFailure
from tests.openai_mock import OpenAIEmbeddingsMock, OpenAIProviderFactory

SUMMARY = "/api/v1/ai-usage/summary"
EVENTS = "/api/v1/ai-usage/events"
BUDGET = "/api/v1/ai-usage/budget"
SMALL = "text-embedding-3-small"


async def _set_limit(session: AsyncSession, limit: str) -> None:
    async with session.begin():
        await session.execute(delete(AiBudget))
        session.add(AiBudget(limit_usd=Decimal(limit)))


async def _all_events() -> list[AiUsageEvent]:
    async with get_sessionmaker()() as session, session.begin():
        return list((await session.scalars(select(AiUsageEvent))).all())


async def _seed_candidates(count: int, *, summary: str | None = None) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for i in range(count):
        payload = valid_candidate_payload(
            full_name=f"Secret Person{i}",
            email=f"secret.person{i}@example.com",
            headline=f"Engineer variant {i}",
            summary=summary or f"Builds backend systems of kind {i} with focus on area {i * 7}.",
        )
        async with get_sessionmaker()() as session:
            created = await create_candidate(
                session, CandidateCreate.model_validate(payload), consent_version="test"
            )
        ids.append(created.id)
    return ids


async def _embed(provider: OpenAIEmbeddingProvider) -> EmbedOutcome:
    async with get_sessionmaker()() as session:
        return await embed_stale(session, provider, CANDIDATES)


async def _metered(session: AsyncSession, call: object, model: str = SMALL) -> int:
    result: int = await metered_call(
        session,
        provider="openai",
        model=model,
        operation="candidate_embedding",
        trigger="worker",
        item_count=1,
        call=call,  # type: ignore[arg-type]  # each test passes a different async stub
        tokens_of=lambda value: (value, 0),
    )
    return result


def _add_spent(session: AsyncSession, cost: str) -> None:
    session.add(
        AiUsageEvent(
            provider="openai",
            model=SMALL,
            operation="candidate_embedding",
            trigger="cli",
            item_count=1,
            input_tokens=1,
            output_tokens=0,
            cost_usd=Decimal(cost),
            status="succeeded",
        )
    )


# --- Cap edges ----------------------------------------------------------------------------


async def test_summary_clamps_remaining_and_reports_over_100_percent_after_overspend(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _set_limit(db_session, "0.02")

    async def big_call() -> int:
        return 4_000_000  # 0.08, allowed because nothing was spent yet

    await _metered(db_session, big_call)

    body = (await admin_client.get(SUMMARY)).json()
    assert Decimal(body["remaining_usd"]) == 0
    assert body["percent_used"] == pytest.approx(400.0)
    assert body["limit_reached"] is True


async def test_a_cancelled_call_records_nothing_and_does_not_block_later_calls(
    db_session: AsyncSession,
) -> None:
    """Documented shortcut: a cancelled call may have been billed but is not recorded."""
    await _set_limit(db_session, "0.02")
    started = asyncio.Event()

    async def slow() -> int:
        started.set()
        await asyncio.sleep(30)
        return 1

    task = asyncio.create_task(_metered(db_session, slow))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _all_events() == []

    async def quick() -> int:
        return 10

    async with get_sessionmaker()() as session:
        assert await _metered(session, quick) == 10


async def test_billed_but_unparseable_response_counts_as_spent_and_blocks_later_calls(
    db_session: AsyncSession,
) -> None:
    await _set_limit(db_session, "0.01")

    async def malformed() -> int:
        raise PermanentEmbeddingError("secret.person@example.com bad", billed_tokens=500_000)

    with pytest.raises(PermanentEmbeddingError):
        await _metered(db_session, malformed)

    [event] = await _all_events()
    assert (event.status, event.input_tokens, event.cost_usd) == (
        "failed",
        500_000,
        Decimal("0.010000"),
    )
    assert event.error is not None and "secret" not in event.error
    async with db_session.begin():
        totals = await repository.totals_by(db_session, AiUsageEvent.model)
    assert [t.cost_usd for t in totals] == [Decimal("0.010000")]
    # The billed cost used up the whole limit, so the next call is refused.
    with pytest.raises(BudgetExceededError):
        await _metered(db_session, malformed)


async def test_failed_rows_without_billing_stay_zero_and_out_of_totals(
    db_session: AsyncSession,
) -> None:
    await _set_limit(db_session, "5.00")
    for billed in (None, 0, -5):

        async def failing(tokens: int | None = billed) -> int:
            raise PermanentEmbeddingError("x", billed_tokens=tokens)

        with pytest.raises(PermanentEmbeddingError):
            await _metered(db_session, failing)

    events = await _all_events()
    assert [e.status for e in events] == ["failed"] * 3
    # A negative count must never become a credit that frees budget.
    assert all((e.input_tokens, e.cost_usd) == (0, Decimal(0)) for e in events)
    async with db_session.begin():
        assert await repository.totals_by(db_session, AiUsageEvent.model) == []
        assert await repository.get_spent(db_session) == 0


async def test_transient_failures_across_retries_never_accumulate_cost(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    await _seed_candidates(1)
    async with get_sessionmaker()() as session:
        await _set_limit(session, "0.02")
    provider = openai_provider(model_name=SMALL)

    for _ in range(3):
        openai_mock.queue_status(503)
        assert (await _embed(provider)).failed == 1
        async with get_sessionmaker()() as session, session.begin():
            # Skip the retry delay.
            await session.execute(
                text("UPDATE embedding_failures SET updated_at = now() - interval '1 day'")
            )
    outcome = await _embed(provider)

    assert outcome.embedded == 1
    events = await _all_events()
    assert sorted(e.status for e in events) == ["failed", "failed", "failed", "succeeded"]
    assert all(e.cost_usd == 0 for e in events if e.status == "failed")
    assert sum(e.cost_usd for e in events) > 0


async def test_permanent_error_in_a_batch_is_isolated_and_costs_nothing_extra(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    await _seed_candidates(3)
    async with get_sessionmaker()() as session:
        await _set_limit(session, "5.00")
    openai_mock.reject_containing = "area 7"

    outcome = await _embed(openai_provider(model_name=SMALL))

    assert (outcome.embedded, outcome.failed) == (2, 1)
    events = await _all_events()
    assert sum(1 for e in events if e.status == "failed") == 2  # whole batch, then the bad one
    assert all(e.cost_usd == 0 for e in events if e.status == "failed")


# --- Re-drive -----------------------------------------------------------------------------


async def test_raised_limit_re_embeds_candidates_the_budget_refused(
    admin_client: AsyncClient, openai_provider: OpenAIProviderFactory
) -> None:
    ids = await _seed_candidates(2)
    async with get_sessionmaker()() as session, session.begin():
        for candidate_id in ids:
            session.add(
                EmbeddingFailure(
                    candidate_id=candidate_id,
                    model=SMALL,
                    content_hash="0" * 64,
                    attempts=1,
                    last_error="budget_exceeded",
                )
            )
    async with get_sessionmaker()() as session:
        await _set_limit(session, "0.00")
    provider = openai_provider(model_name=SMALL)
    assert (await _embed(provider)).embedded == 0
    assert (await admin_client.get(SUMMARY)).json()["limit_reached"] is True

    body = (await admin_client.put(BUDGET, json={"limit_usd": "5.00"})).json()
    assert body["limit_reached"] is False

    assert (await _embed(provider)).embedded == 2
    async with get_sessionmaker()() as session, session.begin():
        assert (await session.scalars(select(EmbeddingFailure))).all() == []


async def test_editing_a_candidate_does_not_bypass_the_cap(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    [candidate_id] = await _seed_candidates(1)
    async with get_sessionmaker()() as session:
        await _set_limit(session, "0.00")
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            text("UPDATE candidates SET search_document = search_document || ' more' WHERE id=:i"),
            {"i": candidate_id},
        )

    outcome = await _embed(openai_provider(model_name=SMALL))

    assert openai_mock.requests == []
    assert outcome.embedded == 0


# --- Privacy ------------------------------------------------------------------------------


async def test_events_and_logs_never_contain_candidate_text(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    openai_mock: OpenAIEmbeddingsMock,
    openai_provider: OpenAIProviderFactory,
) -> None:
    ids = await _seed_candidates(2)
    async with get_sessionmaker()() as session:
        await _set_limit(session, "5.00")
    provider = openai_provider(model_name=SMALL)
    # The provider's error body can echo the input; it must reach neither logs nor events.
    openai_mock.queue_body(
        {"error": {"message": "secret.person0@example.com leaked", "type": "invalid_request"}},
        status=400,
    )
    caplog.set_level(logging.DEBUG)
    caplog.clear()
    capsys.readouterr()

    await _embed(provider)

    captured = capsys.readouterr()
    rows = [
        (e.provider, e.model, e.operation, e.trigger, e.status, e.error)
        for e in await _all_events()
    ]
    haystack = caplog.text + captured.out + captured.err + repr(rows)
    for needle in ("secret.person", "Secret Person", "Builds backend"):
        assert needle not in haystack, needle
    assert not any(str(candidate_id) in repr(rows) for candidate_id in ids)


# --- API validation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"limit_usd": NaN}',
        '{"limit_usd": Infinity}',
        '{"limit_usd": -Infinity}',
        '{"limit_usd": "NaN"}',
        '{"limit_usd": "Infinity"}',
        '{"limit_usd": "abc"}',
        '{"limit_usd": ""}',
        '{"limit_usd": null}',
        '{"limit_usd": true}',
        '{"limit_usd": [5]}',
        '{"limit_usd": {"a": 1}}',
        '{"limit_usd": 5.001}',
        '{"limit_usd": "10000.01"}',
        '{"limit_usd": 1e400}',
        '{"limit_usd": "1e5"}',
        '{"limit_usd": "-0.01"}',
        '{"limit_usd": "5\\u0000"}',
        '{"limit_usd": "5", "limit": 1}',
        "[]",
        "null",
        "5",
    ],
)
async def test_put_budget_rejects_bad_values_with_422_and_leaves_limit_unchanged(
    admin_client: AsyncClient, raw: str
) -> None:
    response = await admin_client.put(
        BUDGET, content=raw, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422, (raw, response.text)
    assert Decimal((await admin_client.get(SUMMARY)).json()["limit_usd"]) == Decimal("5.00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"limit_usd": "0"}', "0.00"),
        ('{"limit_usd": 0}', "0.00"),
        ('{"limit_usd": "10000.00"}', "10000.00"),
        ('{"limit_usd": 7.5}', "7.50"),
        ('{"limit_usd": "0.1"}', "0.10"),
    ],
)
async def test_put_budget_accepts_boundary_values(
    admin_client: AsyncClient, raw: str, expected: str
) -> None:
    response = await admin_client.put(
        BUDGET, content=raw, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200, response.text
    assert Decimal(response.json()["limit_usd"]) == Decimal(expected)


async def test_put_budget_sets_updated_by_and_changes_updated_at(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    before = (await admin_client.get(SUMMARY)).json()["updated_at"]
    await admin_client.put(BUDGET, json={"limit_usd": "6"})
    after = (await admin_client.get(SUMMARY)).json()["updated_at"]

    assert before is None or after != before
    async with db_session.begin():
        budget = (await db_session.scalars(select(AiBudget))).one()
    assert budget.updated_by is not None


async def test_unauthenticated_put_and_unknown_routes(client: AsyncClient) -> None:
    response = await client.put(
        BUDGET, json={"limit_usd": "1"}, headers={"X-Requested-With": "fetch"}
    )
    assert response.status_code == 401
    assert (await client.delete(BUDGET)).status_code in {401, 403, 405}


@pytest.mark.parametrize(
    "params",
    [
        {"model": "a\x00b"},
        {"operation": "a\x00b"},
        {"status": "weird"},
        {"status": "reserved"},  # no longer a status
        {"limit": 0},
        {"limit": -1},
        {"limit": "abc"},
        {"bogus": "1"},
        {"cursor": "x" * 501},
    ],
)
async def test_event_filter_validation(
    admin_client: AsyncClient, params: dict[str, object]
) -> None:
    response = await admin_client.get(EVENTS, params=params)  # type: ignore[arg-type]

    assert response.status_code in {400, 422}, (params, response.status_code)


async def test_sql_metacharacters_in_filters_are_just_values(admin_client: AsyncClient) -> None:
    response = await admin_client.get(EVENTS, params={"model": "'; DROP TABLE ai_usage_events;--"})

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_cursor_with_far_future_or_huge_values_is_a_400_not_500(
    admin_client: AsyncClient,
) -> None:
    from app.core.pagination import encode_cursor

    for key in ("9999-12-31T23:59:59+00:00", "2026-10-29T10:00:00+99:00", "2026-10-29 10:00:00Z"):
        response = await admin_client.get(
            EVENTS, params={"cursor": encode_cursor({"key": key, "id": str(uuid.uuid4())})}
        )
        assert response.status_code in {200, 400}, (key, response.status_code)


# --- Totals -------------------------------------------------------------------------------


async def test_totals_by_model_and_operation_add_up_to_spent(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _set_limit(db_session, "50.00")

    async def spend(model: str, operation: str, tokens: int, *, fail: bool = False) -> None:
        async def call() -> int:
            if fail:
                raise RuntimeError("x")
            return tokens

        try:
            await metered_call(
                db_session,
                provider="openai",
                model=model,
                operation=operation,
                trigger="cli",
                item_count=1,
                call=call,
                tokens_of=lambda value: (value, 0),
            )
        except RuntimeError:
            assert fail

    await spend(SMALL, "candidate_embedding", 123_457)
    await spend(SMALL, "job_embedding", 77_001)
    await spend("text-embedding-3-large", "candidate_embedding", 5_000_003)
    await spend(SMALL, "rerank", 999, fail=True)  # free: not in the tables

    body = (await admin_client.get(SUMMARY)).json()

    spent = Decimal(body["spent_usd"])
    assert spent > 0
    assert sum(Decimal(r["cost_usd"]) for r in body["by_model"]) == spent
    assert sum(Decimal(r["cost_usd"]) for r in body["by_operation"]) == spent
    assert "rerank" not in {r["key"] for r in body["by_operation"]}


async def test_summary_and_events_work_with_a_directly_inserted_row(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _set_limit(db_session, "5.00")
    async with db_session.begin():
        _add_spent(db_session, "0.000001")

    assert (await admin_client.get(SUMMARY)).status_code == 200
    assert (await admin_client.get(EVENTS)).status_code == 200


async def test_lowering_the_limit_below_the_spend_turns_the_flag_on(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _set_limit(db_session, "5.00")
    async with db_session.begin():
        _add_spent(db_session, "0.50")
    assert (await admin_client.get(SUMMARY)).json()["limit_reached"] is False

    body = (await admin_client.put(BUDGET, json={"limit_usd": "0.50"})).json()

    assert body["limit_reached"] is True
