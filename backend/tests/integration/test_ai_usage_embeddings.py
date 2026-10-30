"""The embedding pipeline under the AI budget cap: real Postgres, real provider, mocked HTTP."""

import asyncio
import sys
import uuid
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, select

from app.cli import main as cli_main
from app.core.ai_pricing import compute_cost_usd
from app.core.db import get_engine, get_sessionmaker
from app.core.embeddings import (
    OpenAIEmbeddingProvider,
    get_embedding_provider,
    use_embedding_provider,
)
from app.features.ai_usage.models import AiBudget, AiUsageEvent
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import CANDIDATES, EmbedOutcome, embed_stale
from app.features.embeddings.models import CandidateEmbedding, EmbeddingFailure
from tests.openai_mock import OpenAIEmbeddingsMock, OpenAIProviderFactory, estimate_tokens

MODEL = "text-embedding-3-small"


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run async helpers from a sync test, leaving no pooled connection tied to the loop."""

    async def runner() -> T:
        try:
            return await coroutine
        finally:
            await get_engine().dispose()

    return asyncio.run(runner())


async def _set_limit(limit: str) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(AiBudget))
        session.add(AiBudget(limit_usd=Decimal(limit)))


async def _seed_unembedded(count: int) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for i in range(count):
        payload = valid_candidate_payload(
            full_name=f"Person Number{i}",
            email=f"person{i}@example.com",
            headline=f"Engineer variant {i}",
            summary=f"Builds backend systems of kind {i} with an unusual focus on area {i * 7}.",
        )
        async with get_sessionmaker()() as session:
            created = await create_candidate(
                session, CandidateCreate.model_validate(payload), consent_version="test"
            )
        ids.append(created.id)
    # Sync tests run the code under test on their own event loops.
    await get_engine().dispose()
    return ids


@pytest.fixture
async def unembedded_ids() -> list[uuid.UUID]:
    return await _seed_unembedded(3)


async def _event_statuses() -> list[str]:
    async with get_sessionmaker()() as session, session.begin():
        rows = await session.scalars(select(AiUsageEvent.status).order_by(AiUsageEvent.created_at))
        return list(rows)


async def _failure_errors() -> list[str]:
    async with get_sessionmaker()() as session, session.begin():
        return list(await session.scalars(select(EmbeddingFailure.last_error)))


async def _embedding_count() -> int:
    async with get_sessionmaker()() as session, session.begin():
        return int(await session.scalar(select(func.count()).select_from(CandidateEmbedding)) or 0)


async def _embed(provider: OpenAIEmbeddingProvider | None = None) -> EmbedOutcome:
    async with get_sessionmaker()() as session:
        return await embed_stale(session, provider or get_embedding_provider(), CANDIDATES)


async def _only_event() -> AiUsageEvent:
    async with get_sessionmaker()() as session, session.begin():
        [event] = (await session.scalars(select(AiUsageEvent))).all()
    return event


def _cli(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
    monkeypatch.setattr(sys, "argv", ["app.cli", *arguments])
    cli_main()


def test_zero_limit_backfill_sends_and_records_nothing(
    unembedded_ids: list[uuid.UUID],
    openai_mock: OpenAIEmbeddingsMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(_set_limit("0.00"))

    _cli(monkeypatch, "embed-backfill")

    assert openai_mock.requests == []
    assert _run(_embedding_count()) == 0
    # The scan doesn't even run while the budget is used up, so nothing is refused or logged.
    assert _run(_event_statuses()) == []
    assert _run(_failure_errors()) == []


def test_raising_the_limit_lets_the_backfill_embed_everything(
    unembedded_ids: list[uuid.UUID],
    openai_provider: OpenAIProviderFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(_set_limit("0.00"))
    _cli(monkeypatch, "embed-backfill")
    assert _run(_embedding_count()) == 0

    _run(_set_limit("5.00"))
    # The CLI closed the provider that the fixture installed, so install a fresh one.
    use_embedding_provider(openai_provider())
    _cli(monkeypatch, "embed-backfill")

    assert _run(_embedding_count()) == 3
    assert _run(_event_statuses()) == ["succeeded"]


async def test_candidates_the_budget_refused_are_retried_once_it_has_room(
    unembedded_ids: list[uuid.UUID], openai_mock: OpenAIEmbeddingsMock
) -> None:
    # A refusal can still happen mid-run (another caller spent the rest first).
    async with get_sessionmaker()() as session, session.begin():
        for candidate_id in unembedded_ids:
            session.add(
                EmbeddingFailure(
                    candidate_id=candidate_id,
                    model=MODEL,
                    content_hash="0" * 64,
                    attempts=1,
                    last_error="budget_exceeded",
                )
            )
    await _set_limit("5.00")

    outcome = await _embed()

    assert outcome.embedded == 3
    assert await _failure_errors() == []


async def test_a_run_records_one_event_with_cost_from_tokens_and_price(
    unembedded_ids: list[uuid.UUID], openai_mock: OpenAIEmbeddingsMock
) -> None:
    await _set_limit("5.00")

    outcome = await _embed()

    assert outcome.embedded == 3
    event = await _only_event()
    assert (event.status, event.trigger, event.operation, event.item_count) == (
        "succeeded",
        "worker",
        "candidate_embedding",
        3,
    )
    assert event.provider == "openai"
    # Exactly the tokens the (mocked) provider billed for the one request.
    [sent] = openai_mock.requests
    assert event.input_tokens == estimate_tokens(sent) > 0
    assert event.cost_usd == compute_cost_usd(MODEL, event.input_tokens)
    assert event.cost_usd > 0


async def test_unknown_model_price_blocks_the_run_without_calling_the_provider(
    unembedded_ids: list[uuid.UUID],
    openai_mock: OpenAIEmbeddingsMock,
    openai_provider: OpenAIProviderFactory,
) -> None:
    await _set_limit("5.00")

    outcome = await _embed(openai_provider(model_name="mystery-model"))

    assert openai_mock.requests == []
    assert outcome.blocked == 3
    assert await _failure_errors() == ["model_price_unknown"] * 3
    assert await _event_statuses() == ["blocked"]
    # Never retried automatically: a price has to be added first.
    assert (await _embed(openai_provider(model_name="mystery-model"))).blocked == 0


async def test_provider_failure_costs_nothing(
    unembedded_ids: list[uuid.UUID], openai_mock: OpenAIEmbeddingsMock
) -> None:
    await _set_limit("5.00")
    openai_mock.queue_status(503)

    outcome = await _embed()

    assert outcome.failed == 3
    event = await _only_event()
    assert (event.status, event.cost_usd) == ("failed", Decimal(0))
    assert event.error == "TransientEmbeddingError status=503"


async def test_a_rejected_200_response_is_recorded_at_the_tokens_it_billed(
    openai_mock: OpenAIEmbeddingsMock,
) -> None:
    await _seed_unembedded(1)
    await _set_limit("5.00")
    ragged = {"object": "embedding", "index": 0, "embedding": [0.5, 0.5]}
    openai_mock.queue_body({"object": "list", "data": [ragged], "usage": {"total_tokens": 500_000}})

    outcome = await _embed()

    assert outcome.failed == 1
    event = await _only_event()
    assert event.status == "failed"
    assert event.input_tokens == 500_000
    assert event.cost_usd == compute_cost_usd(MODEL, 500_000)
