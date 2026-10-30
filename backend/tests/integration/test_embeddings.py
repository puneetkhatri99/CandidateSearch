"""The embedding pipeline against real Postgres + pgvector, with OpenAI's HTTP layer mocked."""

import asyncio
import sys
import uuid
from collections.abc import Coroutine
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.elements import ClauseElement

from app.cli import main as cli_main
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.embeddings import get_embedding_provider, use_embedding_provider
from app.features.ai_usage.models import AiUsageEvent
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.models import Candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import (
    CANDIDATES,
    EmbedOutcome,
    embed_stale,
    nearest_candidates_to_vector,
    repository,
)
from app.features.embeddings.models import CandidateEmbedding, EmbeddingFailure
from app.features.embeddings.service import hash_document
from tests.openai_mock import OpenAIEmbeddingsMock, deterministic_vector

ADMIN_URL = "/api/v1/admin/candidates"
MODEL = get_settings().embedding_model


class _Explain(Executable, ClauseElement):
    inherit_cache = False

    def __init__(self, statement: Any) -> None:
        self.statement = statement


@compiles(_Explain, "postgresql")
def _compile_explain(element: _Explain, compiler: Any, **kw: Any) -> str:
    return f"EXPLAIN {compiler.process(element.statement, **kw)}"


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run async helpers from a sync test, leaving no pooled connection tied to the loop."""

    async def runner() -> T:
        try:
            return await coroutine
        finally:
            await get_engine().dispose()

    return asyncio.run(runner())


async def _seed(**overrides: Any) -> uuid.UUID:
    payload = valid_candidate_payload(**overrides)
    async with get_sessionmaker()() as session:
        created = await create_candidate(
            session, CandidateCreate.model_validate(payload), consent_version="test"
        )
    return created.id


async def _seed_many(count: int) -> list[uuid.UUID]:
    return [
        await _seed(
            full_name=f"Person Number{i}",
            email=f"person{i}@example.com",
            headline=f"Engineer variant {i}",
            summary=f"Builds backend systems of kind {i} with an unusual focus on area {i * 7}.",
        )
        for i in range(count)
    ]


async def _embed() -> EmbedOutcome:
    async with get_sessionmaker()() as session:
        return await embed_stale(session, get_embedding_provider(), CANDIDATES)


async def _stale(model: str = MODEL) -> list[uuid.UUID]:
    async with get_sessionmaker()() as session, session.begin():
        return await repository.find_stale_ids(session, model, 100, target=CANDIDATES)


async def _count(session: AsyncSession, model: Any) -> int:
    session.expire_all()
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _stored_hash(session: AsyncSession, candidate_id: uuid.UUID) -> str | None:
    return await session.scalar(
        select(CandidateEmbedding.content_hash).where(
            CandidateEmbedding.candidate_id == candidate_id
        )
    )


async def _search_document(session: AsyncSession, candidate_id: uuid.UUID) -> str:
    document = await session.scalar(
        select(Candidate.search_document).where(Candidate.id == candidate_id)
    )
    assert document is not None
    return document


async def _admin_body(admin_client: AsyncClient, candidate_id: uuid.UUID) -> dict[str, Any]:
    detail = (await admin_client.get(f"{ADMIN_URL}/{candidate_id}")).json()
    keys = [
        "full_name",
        "email",
        "phone",
        "city",
        "country_code",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        "headline",
        "years_experience",
        "skills",
        "summary",
        "experiences",
        "educations",
        "desired_roles",
        "work_modes",
        "open_to_relocation",
        "notice_period_days",
        "version",
    ]
    return {key: detail[key] for key in keys}


async def _age_failures() -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            text("UPDATE embedding_failures SET updated_at = now() - interval '1 day'")
        )


# --- Saving makes a candidate stale; the scan embeds it ------------------------------------


async def test_creating_a_candidate_never_embeds_inline_and_leaves_it_stale(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    candidate_id = await _seed()

    assert await _stale() == [candidate_id]
    assert await _count(db_session, CandidateEmbedding) == 0
    assert openai_mock.requests == []


async def test_a_run_embeds_the_candidate_and_stores_its_hash(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    candidate_id = await _seed()

    outcome = await _embed()

    assert outcome.embedded == 1
    assert await _stale() == []
    assert await _stored_hash(db_session, candidate_id) == hash_document(
        await _search_document(db_session, candidate_id)
    )
    assert len(openai_mock.requests) == 1


async def test_honeypot_submission_leaves_nothing_to_embed(
    openai_mock: OpenAIEmbeddingsMock,
) -> None:
    async with get_sessionmaker()() as session:
        await create_candidate(
            session,
            CandidateCreate.model_validate(valid_candidate_payload(website="http://spam.example")),
            consent_version="test",
        )

    assert await _stale() == []
    assert (await _embed()).embedded == 0
    assert openai_mock.requests == []


async def test_unchanged_resave_makes_zero_provider_calls(
    admin_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    candidate_id = await _seed()
    await _embed()

    response = await admin_client.put(
        f"{ADMIN_URL}/{candidate_id}", json=await _admin_body(admin_client, candidate_id)
    )
    assert response.status_code == 200, response.text
    await _embed()

    assert len(openai_mock.requests) == 1
    assert await _count(db_session, CandidateEmbedding) == 1


async def test_edited_profile_is_embedded_again_with_new_hash(
    admin_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    candidate_id = await _seed()
    await _embed()
    old_hash = await _stored_hash(db_session, candidate_id)
    body = await _admin_body(admin_client, candidate_id)

    response = await admin_client.put(
        f"{ADMIN_URL}/{candidate_id}", json={**body, "headline": "Principal Data Architect"}
    )
    assert response.status_code == 200, response.text
    await _embed()

    db_session.expire_all()
    new_hash = await _stored_hash(db_session, candidate_id)
    assert new_hash != old_hash
    assert new_hash == hash_document(await _search_document(db_session, candidate_id))
    assert len(openai_mock.requests) == 2
    assert await _count(db_session, CandidateEmbedding) == 1


async def test_staff_created_candidate_is_embedded(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = valid_candidate_payload(email="staff.made@example.com")
    del payload["consent"]

    response = await admin_client.post(ADMIN_URL, json={**payload, "consent_confirmed": True})

    assert response.status_code == 201, response.text
    await _embed()
    assert await _count(db_session, CandidateEmbedding) == 1


async def test_an_edit_during_the_provider_call_is_embedded_on_the_next_run(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    candidate_id = await _seed()

    async def edit_during_the_provider_call(_: list[str]) -> None:
        async with get_sessionmaker()() as session, session.begin():
            await session.execute(
                text("UPDATE candidates SET search_document = 'edited document' WHERE id = :id"),
                {"id": candidate_id},
            )

    openai_mock.on_request = edit_during_the_provider_call
    await _embed()
    openai_mock.on_request = None

    # The stored hash is of the text that was sent, so the edit still looks stale.
    assert await _stale() == [candidate_id]
    await _embed()
    assert await _stored_hash(db_session, candidate_id) == hash_document("edited document")


async def test_a_database_error_after_the_call_raises_and_the_candidate_stays_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _seed_many(2)

    async def broken(*_: object, **__: object) -> None:
        raise RuntimeError("database write failed")

    monkeypatch.setattr(repository, "upsert_embeddings", broken)

    # The maintenance runner logs it and tries again later.
    with pytest.raises(RuntimeError):
        await _embed()

    assert sorted(await _stale()) == sorted(ids)
    async with get_sessionmaker()() as session, session.begin():
        statuses = list(await session.scalars(select(AiUsageEvent.status)))
    assert statuses == ["succeeded"]  # billed, so recorded


# --- Failures and the dead letter -------------------------------------------------------------


async def test_permanent_failure_is_not_retried_until_an_edit(
    admin_client: AsyncClient, db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    openai_mock.queue_status(400)
    candidate_id = await _seed()

    assert (await _embed()).failed == 1

    failure = (await db_session.execute(select(EmbeddingFailure))).scalar_one()
    document = await _search_document(db_session, candidate_id)
    assert failure.candidate_id == candidate_id
    assert failure.content_hash == hash_document(document)
    assert failure.last_error == "PermanentEmbeddingError status=400"
    assert failure.attempts == 1
    await _age_failures()
    assert await _stale() == []  # retrying the same text would fail the same way

    # Editing changes the document, so it is embedded again and the dead letter is cleared.
    body = await _admin_body(admin_client, candidate_id)
    response = await admin_client.put(
        f"{ADMIN_URL}/{candidate_id}", json={**body, "headline": "Staff Engineer"}
    )
    assert response.status_code == 200
    await _embed()
    assert await _count(db_session, EmbeddingFailure) == 0
    assert await _count(db_session, CandidateEmbedding) == 1


async def test_transient_failure_waits_out_its_retry_delay(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    openai_mock.queue_status(503)
    await _seed()

    assert (await _embed()).failed == 1

    failure = (await db_session.execute(select(EmbeddingFailure))).scalar_one()
    assert failure.last_error == "TransientEmbeddingError status=503"
    assert await _stale() == []  # not due for 30 s
    await _age_failures()
    assert (await _embed()).embedded == 1


async def test_repeated_failures_for_the_same_text_count_attempts(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    await _seed()
    openai_mock.queue_status(503)
    openai_mock.queue_status(503)

    await _embed()
    await _age_failures()
    await _embed()

    failure = (await db_session.execute(select(EmbeddingFailure))).scalar_one()
    assert failure.attempts == 2


# --- The stale scan ---------------------------------------------------------------------------


async def test_stale_scan_selects_missing_stale_and_old_failures_but_not_current_ones(
    db_session: AsyncSession,
) -> None:
    fresh, missing, stale, dead_current, dead_old = [
        await _seed(email=f"sweep{i}@example.com", full_name=f"Sweep Person{i}") for i in range(5)
    ]
    vector = [0.1] * 1536

    def add_embedding(candidate_id: uuid.UUID, content_hash: str) -> None:
        db_session.add(
            CandidateEmbedding(
                candidate_id=candidate_id, model=MODEL, content_hash=content_hash, embedding=vector
            )
        )

    def add_failure(candidate_id: uuid.UUID, content_hash: str) -> None:
        db_session.add(
            EmbeddingFailure(
                candidate_id=candidate_id,
                model=MODEL,
                content_hash=content_hash,
                attempts=3,
                last_error="PermanentEmbeddingError status=400",
            )
        )

    add_embedding(fresh, hash_document(await _search_document(db_session, fresh)))
    add_embedding(stale, "0" * 64)
    add_failure(dead_current, hash_document(await _search_document(db_session, dead_current)))
    add_failure(dead_old, "f" * 64)
    await db_session.commit()

    assert set(await _stale()) == {missing, stale, dead_old}


async def test_embeddings_for_another_model_do_not_count_as_current() -> None:
    candidate_id = await _seed()
    await _embed()

    assert await _stale("some-newer-model") == [candidate_id]


async def test_sql_hash_matches_python_hash_for_unicode_documents(
    db_session: AsyncSession,
) -> None:
    candidate_id = await _seed(
        headline="Ingénieur logiciel 日本語", summary="Résumé détaillé ✓ " * 5
    )
    await _embed()

    assert await _stale() == []
    assert await _stored_hash(db_session, candidate_id) == hash_document(
        await _search_document(db_session, candidate_id)
    )


async def test_a_run_takes_at_most_one_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "embedding_batch_size", 2)
    await _seed_many(5)

    assert (await _embed()).embedded == 2
    assert len(await _stale()) == 3


# --- Cascade, similarity, readiness -----------------------------------------------------------


async def test_deleting_a_candidate_cascades_to_both_tables(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    embedded = await _seed()
    await _embed()
    openai_mock.queue_status(400)
    dead_lettered = await _seed(email="other@example.com", full_name="Other Person")
    await _embed()
    assert await _count(db_session, CandidateEmbedding) == 1
    assert await _count(db_session, EmbeddingFailure) == 1

    await db_session.execute(delete(Candidate).where(Candidate.id.in_([embedded, dead_lettered])))
    await db_session.commit()

    assert await _count(db_session, CandidateEmbedding) == 0
    assert await _count(db_session, EmbeddingFailure) == 0


async def test_nearest_candidates_are_ranked_by_cosine_similarity(
    db_session: AsyncSession,
) -> None:
    ids = await _seed_many(4)
    await _embed()
    query = deterministic_vector(await _search_document(db_session, ids[0]))

    async with get_sessionmaker()() as session:
        nearest = await nearest_candidates_to_vector(session, query, MODEL, count=10)

    assert nearest[0][0] == ids[0]
    assert nearest[0][1] == pytest.approx(1.0, abs=1e-6)
    assert {candidate_id for candidate_id, _ in nearest} == set(ids)
    scores = [score for _, score in nearest]
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0001 <= score <= 1.0001 for score in scores)


async def test_identical_documents_have_similarity_one(db_session: AsyncSession) -> None:
    first = await _seed(email="twin1@example.com", full_name="Twin One")
    await _seed(email="twin2@example.com", full_name="Twin Two")
    await _embed()
    query = deterministic_vector(await _search_document(db_session, first))

    async with get_sessionmaker()() as session:
        nearest = await nearest_candidates_to_vector(session, query, MODEL, count=5)

    # Names are redacted from the search document, so otherwise-equal profiles embed alike.
    assert [score for _, score in nearest] == pytest.approx([1.0, 1.0], abs=1e-6)


async def test_similarity_query_uses_the_hnsw_index(db_session: AsyncSession) -> None:
    # On a near-empty table the planner prefers a plain sort, so load enough rows for the index
    # to win. Everything runs in one transaction that is rolled back, so the synthetic rows and
    # the index rebuild vanish: the index is dropped first so the bulk insert is not slowed by
    # incremental HNSW inserts, then recreated with the production definition. Foreign keys are
    # skipped (replica role) because only the plan matters.
    statement = repository.similarity_statement([0.01] * 1536, MODEL, 3)
    async with db_session.begin():
        await db_session.execute(text("DROP INDEX ix_candidate_embeddings_embedding_hnsw"))
        await db_session.execute(text("SET LOCAL session_replication_role = replica"))
        await db_session.execute(
            text(
                "INSERT INTO candidate_embeddings"
                " (id, candidate_id, model, content_hash, embedding)"
                " SELECT gen_random_uuid(), gen_random_uuid(), :model, repeat('a', 64),"
                " (SELECT array_agg(random()::real) FROM generate_series(1, 1536)"
                "  WHERE g.i > 0)::vector"
                " FROM generate_series(1, 1500) AS g(i)"
            ),
            {"model": MODEL},
        )
        await db_session.execute(text("ANALYZE candidate_embeddings"))
        await db_session.execute(
            text(
                "CREATE INDEX ix_candidate_embeddings_embedding_hnsw"
                " ON candidate_embeddings USING hnsw (embedding vector_cosine_ops)"
            )
        )
        await db_session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(str(row[0]) for row in await db_session.execute(_Explain(statement)))
        await db_session.rollback()
    assert "Index Scan using ix_candidate_embeddings_embedding_hnsw" in plan, plan[:600]


async def test_hnsw_index_is_declared_with_cosine_ops(db_session: AsyncSession) -> None:
    definition = await db_session.scalar(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'ix_candidate_embeddings_embedding_hnsw'"
        )
    )

    assert definition is not None
    assert "USING hnsw" in definition
    assert "vector_cosine_ops" in definition


async def test_readiness_reports_only_database_and_pgvector(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": True, "pgvector": True},
    }


async def test_candidate_response_never_contains_embedding_internals(
    admin_client: AsyncClient,
) -> None:
    candidate_id = await _seed()

    body = (await admin_client.get(f"{ADMIN_URL}/{candidate_id}")).text

    assert "embedding" not in body
    assert "content_hash" not in body


# --- CLI (sync tests: the CLI runs its own event loop) ----------------------------------------


@pytest.fixture
async def unembedded_candidate_id() -> uuid.UUID:
    candidate_id = await _seed()
    # Sync tests run the code under test on their own event loops; pooled asyncpg connections
    # opened here must not leak into them.
    await get_engine().dispose()
    return candidate_id


async def _embedding_count() -> int:
    async with get_sessionmaker()() as session:
        return await _count(session, CandidateEmbedding)


def _cli(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
    monkeypatch.setattr(sys, "argv", ["app.cli", *arguments])
    cli_main()


def test_cli_backfill_embeds_and_exits(
    unembedded_candidate_id: uuid.UUID,
    openai_mock: OpenAIEmbeddingsMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cli(monkeypatch, "embed-backfill")

    assert len(openai_mock.requests) == 1
    assert _run(_embedding_count()) == 1


def test_cli_maintenance_once_embeds_too(
    unembedded_candidate_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cli(monkeypatch, "maintenance", "--once")

    assert _run(_embedding_count()) == 1


def test_cli_backfill_exits_with_code_one_without_a_real_api_key(
    unembedded_candidate_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_embedding_provider(None)
    monkeypatch.setattr(get_settings(), "openai_api_key", None)

    with pytest.raises(SystemExit) as raised:
        _cli(monkeypatch, "embed-backfill")

    assert raised.value.code == 1
    assert _run(_embedding_count()) == 0
