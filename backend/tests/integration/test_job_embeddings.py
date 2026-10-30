"""Job role embeddings through the shared stale scan, with OpenAI's HTTP layer mocked."""

import asyncio
import sys
import uuid
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import main as cli_main
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.embeddings import get_embedding_provider
from app.features.ai_usage.models import AiBudget, AiUsageEvent
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import (
    CANDIDATES,
    JOBS,
    EmbedOutcome,
    embed_all_stale,
    embed_stale,
    get_job_embedding_status,
)
from app.features.embeddings.models import CandidateEmbedding, JobEmbedding, JobEmbeddingFailure
from app.features.embeddings.service import hash_document
from app.features.embeddings.targets import EmbeddingTarget
from app.features.jobs.models import Job
from tests.integration.conftest import create_job
from tests.openai_mock import OpenAIEmbeddingsMock

URL = "/api/v1/jobs"
MODEL = get_settings().embedding_model


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    async def runner() -> T:
        try:
            return await coroutine
        finally:
            await get_engine().dispose()

    return asyncio.run(runner())


async def _embed(target: EmbeddingTarget = JOBS) -> EmbedOutcome:
    async with get_sessionmaker()() as session:
        return await embed_stale(session, get_embedding_provider(), target)


async def _set_limit(limit: str) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(AiBudget))
        session.add(AiBudget(limit_usd=Decimal(limit)))


async def _count(db_session: AsyncSession, model: Any) -> int:
    db_session.expire_all()
    return int(await db_session.scalar(select(func.count()).select_from(model)) or 0)


async def _status(job_id: str) -> str:
    async with get_sessionmaker()() as session, session.begin():
        status: str = await get_job_embedding_status(session, uuid.UUID(job_id), MODEL)
        return status


async def _document(db_session: AsyncSession) -> str:
    db_session.expire_all()
    document = await db_session.scalar(select(Job.search_document))
    assert document is not None
    return str(document)


async def _patch(client: AsyncClient, job: dict[str, Any], **changes: Any) -> dict[str, Any]:
    response = await client.patch(f"{URL}/{job['id']}", json={"version": job["version"], **changes})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- Embedding a job -----------------------------------------------------------------------


async def test_a_run_embeds_exactly_the_search_document_and_meters_it(
    recruiter_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    job = await create_job(recruiter_client)
    document = await _document(db_session)

    outcome = await _embed()

    assert outcome.embedded == 1
    assert openai_mock.requests == [[document]]
    stored = await db_session.scalar(select(JobEmbedding))
    assert stored is not None
    assert (str(stored.job_id), stored.model) == (job["id"], MODEL)
    assert stored.content_hash == hash_document(document)
    dimensions = await db_session.scalar(select(func.vector_dims(JobEmbedding.embedding)))
    assert dimensions == 1536  # same dimensions as candidate vectors
    [event] = (await db_session.scalars(select(AiUsageEvent))).all()
    assert (event.operation, event.trigger, event.provider, event.status) == (
        "job_embedding",
        "worker",
        "openai",
        "succeeded",
    )
    assert await _status(job["id"]) == "ready"


async def test_saving_a_job_never_calls_openai(
    recruiter_client: AsyncClient, openai_mock: OpenAIEmbeddingsMock
) -> None:
    await create_job(recruiter_client)

    assert openai_mock.requests == []


async def test_closing_a_job_or_resaving_identical_text_makes_zero_calls(
    recruiter_client: AsyncClient, openai_mock: OpenAIEmbeddingsMock
) -> None:
    job = await create_job(recruiter_client, status="open")
    await _embed()
    calls = len(openai_mock.requests)

    job = await _patch(recruiter_client, job, status="closed")
    closed_run = await _embed()
    job = await _patch(recruiter_client, job, title=job["title"])
    same_run = await _embed()

    # Neither edit changes the document, so nothing is stale.
    assert (closed_run.embedded, same_run.embedded) == (0, 0)
    assert len(openai_mock.requests) == calls


async def test_changed_text_is_embedded_again_and_replaces_the_row(
    recruiter_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    job = await create_job(recruiter_client)
    await _embed()
    first_hash = await db_session.scalar(select(JobEmbedding.content_hash))

    await _patch(recruiter_client, job, title="Principal Backend Engineer")
    assert await _status(job["id"]) == "pending"
    await _embed()

    db_session.expire_all()
    assert await _count(db_session, JobEmbedding) == 1
    new_hash = await db_session.scalar(select(JobEmbedding.content_hash))
    assert new_hash != first_hash
    assert new_hash == hash_document(await _document(db_session))
    assert len(openai_mock.requests) == 2


async def test_candidates_and_jobs_are_embedded_separately_with_their_own_operations(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_job(recruiter_client)
    async with get_sessionmaker()() as session:
        await create_candidate(
            session,
            CandidateCreate.model_validate(valid_candidate_payload()),
            consent_version="test",
        )

    jobs_run = await _embed(JOBS)
    assert await _count(db_session, CandidateEmbedding) == 0  # the candidate is untouched
    candidates_run = await _embed(CANDIDATES)

    assert (jobs_run.embedded, candidates_run.embedded) == (1, 1)
    operations = sorted(await db_session.scalars(select(AiUsageEvent.operation)))
    assert operations == ["candidate_embedding", "job_embedding"]
    assert await _count(db_session, JobEmbedding) == 1


async def test_one_pass_embeds_a_new_job_even_behind_a_candidate_backlog(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    for index in range(70):
        async with get_sessionmaker()() as session:
            await create_candidate(
                session,
                CandidateCreate.model_validate(
                    valid_candidate_payload(email=f"backlog{index}@example.com")
                ),
                consent_version="test",
            )
    await create_job(recruiter_client)

    async with get_sessionmaker()() as session:
        await embed_all_stale(session, get_embedding_provider())

    assert await _count(db_session, JobEmbedding) == 1  # jobs go first
    assert await _count(db_session, CandidateEmbedding) == 64  # one candidate batch per pass


# --- Failures ------------------------------------------------------------------------------


async def test_a_transient_failure_is_recorded_and_retried_later(
    recruiter_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    job = await create_job(recruiter_client)
    openai_mock.queue_status(503)

    assert (await _embed()).failed == 1

    failure = await db_session.scalar(select(JobEmbeddingFailure))
    assert failure is not None
    assert failure.last_error == "TransientEmbeddingError status=503"
    assert (await _embed()).embedded == 0  # retry delay: not due yet
    assert await _status(job["id"]) == "pending"


async def test_a_permanent_failure_is_dead_lettered_until_the_text_changes(
    recruiter_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    job = await create_job(recruiter_client)
    openai_mock.queue_status(400)
    await _embed()
    assert await _count(db_session, JobEmbeddingFailure) == 1
    assert await _status(job["id"]) == "failed"
    calls = len(openai_mock.requests)

    # Even long after, the same text is not sent again.
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            text("UPDATE job_embedding_failures SET updated_at = now() - interval '30 days'")
        )
    assert (await _embed()).embedded == 0
    assert len(openai_mock.requests) == calls

    # An edit changes the hash, so it is tried again.
    await _patch(recruiter_client, job, title="A different title")
    await _embed()
    assert len(openai_mock.requests) == calls + 1
    assert await _count(db_session, JobEmbedding) == 1
    assert await _count(db_session, JobEmbeddingFailure) == 0


# --- Budget --------------------------------------------------------------------------------


async def test_at_a_zero_limit_the_job_saves_and_waits_without_any_call(
    recruiter_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    await _set_limit("0.00")

    job = await create_job(recruiter_client)  # 201 despite the exhausted budget
    outcome = await _embed()

    assert outcome.embedded == 0
    assert openai_mock.requests == []
    assert (await db_session.scalars(select(AiUsageEvent))).all() == []
    assert await _status(job["id"]) == "budget_blocked"

    await _set_limit("5.00")
    assert await _status(job["id"]) == "pending"
    assert (await _embed()).embedded == 1
    assert await _status(job["id"]) == "ready"


# --- Status, cascade, CLI ------------------------------------------------------------------


async def test_get_job_embedding_status_returns_each_state(
    recruiter_client: AsyncClient, openai_mock: OpenAIEmbeddingsMock
) -> None:
    pending = await create_job(recruiter_client, title="Pending role")
    assert await _status(pending["id"]) == "pending"
    await _embed()
    assert await _status(pending["id"]) == "ready"

    failed = await create_job(recruiter_client, title="Failed role")
    openai_mock.queue_status(400)
    await _embed()
    assert await _status(failed["id"]) == "failed"

    await _set_limit("0.00")
    blocked = await create_job(recruiter_client, title="Blocked role")
    assert await _status(blocked["id"]) == "budget_blocked"


async def test_deleting_a_job_cascades_to_its_embedding_tables(
    recruiter_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    await create_job(recruiter_client, title="Embedded role")
    await _embed()
    await create_job(recruiter_client, title="Failed role")
    openai_mock.queue_status(400)
    await _embed()

    async with get_sessionmaker()() as session, session.begin():
        await session.execute(text("DELETE FROM jobs"))

    for model in (JobEmbedding, JobEmbeddingFailure):
        assert await _count(db_session, model) == 0


@pytest.fixture
async def saved_job(recruiter_client: AsyncClient) -> None:
    await create_job(recruiter_client)
    await get_engine().dispose()  # the sync CLI test below runs on its own event loop


async def _triggers() -> list[tuple[str, str]]:
    async with get_sessionmaker()() as session, session.begin():
        rows = await session.execute(select(AiUsageEvent.operation, AiUsageEvent.trigger))
        return [(row[0], row[1]) for row in rows]


def test_backfill_embeds_jobs_with_the_cli_trigger(
    saved_job: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["app.cli", "embed-backfill"])

    cli_main()

    assert _run(_triggers()) == [("job_embedding", "cli")]
