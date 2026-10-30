"""QA edge cases for the embedding pipeline: PII, logging and the provider fallback."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.embeddings import get_embedding_provider
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.models import Candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import CANDIDATES, EmbedOutcome, embed_stale
from app.features.embeddings.models import CandidateEmbedding, EmbeddingFailure
from tests.openai_mock import OpenAIEmbeddingsMock


async def _seed(**overrides: Any) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        created = await create_candidate(
            session,
            CandidateCreate.model_validate(valid_candidate_payload(**overrides)),
            consent_version="test",
        )
    return created.id


async def _embed() -> EmbedOutcome:
    async with get_sessionmaker()() as session:
        return await embed_stale(session, get_embedding_provider(), CANDIDATES)


async def test_only_the_redacted_search_document_reaches_the_provider(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    candidate_id = await _seed(
        full_name="Zephyrine Quillfeather",
        email="zephyrine.quill@example.com",
        phone="+14155550123",
    )
    await _embed()

    document = await db_session.scalar(
        select(Candidate.search_document).where(Candidate.id == candidate_id)
    )
    # Exactly what went over the wire: one request carrying the redacted document and nothing else.
    assert openai_mock.requests == [[document]]
    blob = "\n".join(openai_mock.requests[0]).lower()
    for secret in ("zephyrine", "quillfeather", "zephyrine.quill", "@example.com", "4155550123"):
        assert secret not in blob
    assert set(openai_mock.payloads[0]) == {"model", "input", "dimensions", "encoding_format"}


async def test_logs_during_embedding_hold_ids_only(capsys: pytest.CaptureFixture[str]) -> None:
    await _seed(
        full_name="Zephyrine Quillfeather",
        email="zephyrine.quill@example.com",
        summary="Highly distinctive summary sentence about quantum widgets and gears.",
    )
    await _embed()
    rendered = capsys.readouterr().out.lower()

    assert "embedding_run_completed" in rendered
    for secret in ("zephyrine", "quillfeather", "quantum widgets", "example.com", "sk-"):
        assert secret not in rendered


async def test_openai_provider_with_mock_transport_dead_letters_only_the_poison_input(
    db_session: AsyncSession, openai_mock: OpenAIEmbeddingsMock
) -> None:
    """End to end through the real provider and SDK: a 400 on a batch falls back one by one."""
    good_a = await _seed(
        email="good.a@example.com",
        summary="Alpha systems engineer who builds reliable data pipelines daily.",
    )
    bad = await _seed(
        email="bad@example.com",
        summary="Contains the POISONWORD marker plus enough padding to be valid.",
    )
    good_b = await _seed(
        email="good.b@example.com",
        summary="Gamma platform engineer who runs large kubernetes clusters well.",
    )
    openai_mock.reject_containing = "POISONWORD"

    outcome = await _embed()

    assert (outcome.embedded, outcome.failed) == (2, 1)
    assert [len(batch) for batch in openai_mock.requests] == [3, 1, 1, 1]
    embedded = set((await db_session.scalars(select(CandidateEmbedding.candidate_id))).all())
    assert embedded == {good_a, good_b}
    failure = (await db_session.execute(select(EmbeddingFailure))).scalar_one()
    assert failure.candidate_id == bad
    assert failure.last_error == "PermanentEmbeddingError status=400"
    assert "mocked rejection" not in failure.last_error
