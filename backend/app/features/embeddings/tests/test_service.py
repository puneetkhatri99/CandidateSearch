"""Service logic against an in-memory repository: no database, the OpenAI HTTP layer is mocked.

Which rows the stale scan picks (retry delays, dead letters) is SQL, tested in
tests/integration/test_embeddings.py and test_embedding_qa.py.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.embeddings import MAX_INPUT_CHARACTERS, OpenAIEmbeddingProvider
from app.features import ai_usage
from app.features.ai_usage import BudgetExceededError
from app.features.embeddings import repository, service
from app.features.embeddings.repository import EmbeddingRow
from app.features.embeddings.targets import CANDIDATES, JOBS, EmbeddingTarget
from tests.openai_mock import OpenAIEmbeddingsMock, OpenAIProviderFactory

DIMENSIONS = 8


class _Session:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


class _MemoryRepository:
    """Stale = no stored hash, or a different one (the SQL also handles dead letters)."""

    def __init__(self) -> None:
        self.documents: dict[uuid.UUID, str] = {}
        self.hashes: dict[uuid.UUID, str] = {}
        self.failures: dict[uuid.UUID, tuple[str, str]] = {}
        self.targets: list[str] = []

    async def find_stale_ids(
        self, _: object, model: str, limit: int, *, target: EmbeddingTarget
    ) -> list[uuid.UUID]:
        self.targets.append(target.name)
        stale = [
            i
            for i, text in self.documents.items()
            if self.hashes.get(i) != service.hash_document(text)
        ]
        return stale[:limit]

    async def load_documents(
        self, _: object, ids: Sequence[uuid.UUID], *, target: EmbeddingTarget
    ) -> dict[uuid.UUID, str]:
        return {i: self.documents[i] for i in ids if i in self.documents}

    async def upsert_embeddings(
        self, _: object, model: str, rows: Sequence[EmbeddingRow], *, target: EmbeddingTarget
    ) -> None:
        for row in rows:
            self.hashes[row.entity_id] = row.content_hash

    async def clear_failures(
        self, _: object, model: str, ids: Sequence[uuid.UUID], *, target: EmbeddingTarget
    ) -> None:
        for i in ids:
            self.failures.pop(i, None)

    async def record_failure(self, _: object, **kwargs: Any) -> None:
        self.failures[kwargs["entity_id"]] = (kwargs["content_hash"], kwargs["error"])


class _Metering:
    """Stands in for ai_usage so these tests need no database."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.refuse: Exception | None = None
        # How many calls go through before `refuse` applies.
        self.refuse_after = 0
        self.budget = True

    async def __call__(self, session: object, *, call: Any, tokens_of: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.refuse is not None and len(self.calls) > self.refuse_after:
            raise self.refuse
        result = await call()
        kwargs["tokens"] = tokens_of(result)
        return result

    async def has_budget(self, _: object) -> bool:
        return self.budget


@pytest.fixture
def metering(monkeypatch: pytest.MonkeyPatch) -> _Metering:
    fake = _Metering()
    monkeypatch.setattr(ai_usage, "metered_call", fake)
    monkeypatch.setattr(ai_usage, "has_budget", fake.has_budget)
    return fake


@pytest.fixture
def memory(metering: _Metering, monkeypatch: pytest.MonkeyPatch) -> _MemoryRepository:
    store = _MemoryRepository()
    for name in (
        "find_stale_ids",
        "load_documents",
        "upsert_embeddings",
        "clear_failures",
        "record_failure",
    ):
        monkeypatch.setattr(repository, name, getattr(store, name))
    return store


@pytest.fixture
def provider(openai_provider: OpenAIProviderFactory) -> OpenAIEmbeddingProvider:
    return openai_provider(dimensions=DIMENSIONS)


def _add(store: _MemoryRepository, text: str) -> uuid.UUID:
    entity_id = uuid.uuid4()
    store.documents[entity_id] = text
    return entity_id


async def _embed(
    provider: OpenAIEmbeddingProvider, target: EmbeddingTarget = CANDIDATES
) -> service.EmbedOutcome:
    return await service.embed_stale(cast(AsyncSession, _Session()), provider, target)


def _texts_sent(mock: OpenAIEmbeddingsMock) -> list[str]:
    return [text for request in mock.requests for text in request]


async def test_new_documents_are_embedded_and_hashed(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider, openai_mock: OpenAIEmbeddingsMock
) -> None:
    a, _ = _add(memory, "doc a"), _add(memory, "doc b")

    outcome = await _embed(provider)

    assert outcome.embedded == 2
    assert memory.hashes[a] == service.hash_document("doc a")
    assert len(_texts_sent(openai_mock)) == 2


async def test_unchanged_documents_make_zero_provider_calls(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider, openai_mock: OpenAIEmbeddingsMock
) -> None:
    _add(memory, "doc a")
    await _embed(provider)

    outcome = await _embed(provider)

    assert outcome.embedded == 0
    assert len(openai_mock.requests) == 1


async def test_changed_document_is_embedded_again(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider
) -> None:
    a = _add(memory, "old")
    await _embed(provider)
    memory.documents[a] = "new"

    outcome = await _embed(provider)

    assert outcome.embedded == 1
    assert memory.hashes[a] == service.hash_document("new")


async def test_nothing_is_sent_while_the_budget_is_used_up(
    memory: _MemoryRepository,
    metering: _Metering,
    provider: OpenAIEmbeddingProvider,
    openai_mock: OpenAIEmbeddingsMock,
) -> None:
    _add(memory, "doc a")
    metering.budget = False

    outcome = await _embed(provider)

    assert (outcome.embedded, outcome.blocked) == (0, 0)
    assert openai_mock.requests == []
    assert memory.targets == []  # not even scanned


async def test_each_run_embeds_one_batch(
    memory: _MemoryRepository,
    provider: OpenAIEmbeddingProvider,
    openai_mock: OpenAIEmbeddingsMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "embedding_batch_size", 2)
    for i in range(5):
        _add(memory, f"doc {i}")

    outcomes = [await _embed(provider) for _ in range(3)]

    assert [len(request) for request in openai_mock.requests] == [2, 2, 1]
    assert [outcome.embedded for outcome in outcomes] == [2, 2, 1]


async def test_long_documents_are_truncated_before_embedding(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider, openai_mock: OpenAIEmbeddingsMock
) -> None:
    a = _add(memory, "y" * (MAX_INPUT_CHARACTERS + 10))

    await _embed(provider)

    assert [len(text) for text in _texts_sent(openai_mock)] == [MAX_INPUT_CHARACTERS]
    # The hash covers the full document, so truncation never causes endless re-embedding.
    assert memory.hashes[a] == service.hash_document("y" * (MAX_INPUT_CHARACTERS + 10))


async def test_transient_error_is_dead_lettered(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider, openai_mock: OpenAIEmbeddingsMock
) -> None:
    a = _add(memory, "doc a")
    openai_mock.queue_status(503)

    outcome = await _embed(provider)

    assert outcome.failed == 1
    assert memory.failures[a] == (
        service.hash_document("doc a"),
        "TransientEmbeddingError status=503",
    )
    assert a not in memory.hashes


async def test_permanent_error_on_single_text_is_dead_lettered(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider, openai_mock: OpenAIEmbeddingsMock
) -> None:
    a = _add(memory, "doc a")
    openai_mock.queue_status(400)

    outcome = await _embed(provider)

    assert outcome.failed == 1
    assert memory.failures[a][1] == "PermanentEmbeddingError status=400"


async def test_permanent_batch_error_falls_back_to_one_by_one(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider, openai_mock: OpenAIEmbeddingsMock
) -> None:
    good1, bad, good2 = _add(memory, "ok 1"), _add(memory, "POISON"), _add(memory, "ok 2")
    openai_mock.reject_containing = "POISON"

    outcome = await _embed(provider)

    assert (outcome.embedded, outcome.failed) == (2, 1)
    assert set(memory.failures) == {bad}
    assert set(memory.hashes) == {good1, good2}


async def test_success_clears_an_earlier_failure(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider, openai_mock: OpenAIEmbeddingsMock
) -> None:
    a = _add(memory, "doc a")
    openai_mock.queue_status(503)
    await _embed(provider)

    await _embed(provider)

    assert a not in memory.failures
    assert a in memory.hashes


async def test_each_batch_is_metered_with_its_real_token_count(
    memory: _MemoryRepository, metering: _Metering, provider: OpenAIEmbeddingProvider
) -> None:
    _add(memory, "doc a")
    _add(memory, "doc b")

    await _embed(provider)

    [call] = metering.calls
    assert call["provider"] == "openai"
    assert call["operation"] == "candidate_embedding"
    assert call["trigger"] == "worker"
    assert call["item_count"] == 2
    assert call["tokens"][0] > 0
    assert call["tokens"][1] == 0  # embeddings have no output tokens


async def test_budget_refusal_dead_letters_the_batch(
    memory: _MemoryRepository,
    metering: _Metering,
    provider: OpenAIEmbeddingProvider,
    openai_mock: OpenAIEmbeddingsMock,
) -> None:
    ids = [_add(memory, f"doc {i}") for i in range(5)]
    metering.refuse = BudgetExceededError("limit reached")

    outcome = await _embed(provider)

    assert openai_mock.requests == []
    assert len(metering.calls) == 1
    assert (outcome.blocked, outcome.embedded) == (5, 0)
    assert {error for _, error in memory.failures.values()} == {"budget_exceeded"}
    assert set(memory.failures) == set(ids)


async def test_a_refusal_during_the_one_by_one_retry_asks_only_once(
    memory: _MemoryRepository,
    metering: _Metering,
    provider: OpenAIEmbeddingProvider,
    openai_mock: OpenAIEmbeddingsMock,
) -> None:
    ids = [_add(memory, "POISON"), _add(memory, "doc 1"), _add(memory, "doc 2")]
    openai_mock.reject_containing = "POISON"
    # The batch call goes through and is rejected; the budget runs out right after.
    metering.refuse = BudgetExceededError("limit reached")
    metering.refuse_after = 1

    outcome = await _embed(provider)

    # One batch call, one refused single call, then no more asking.
    assert len(metering.calls) == 2
    assert outcome.blocked == 3
    assert set(memory.failures) == set(ids)


async def test_job_embeddings_use_the_job_target_and_operation(
    memory: _MemoryRepository, metering: _Metering, provider: OpenAIEmbeddingProvider
) -> None:
    _add(memory, "job doc")

    await _embed(provider, target=JOBS)

    assert metering.calls[0]["operation"] == "job_embedding"
    assert memory.targets == ["job"]


async def test_embed_all_stale_does_jobs_before_candidates(
    memory: _MemoryRepository, provider: OpenAIEmbeddingProvider
) -> None:
    _add(memory, "doc")

    embedded = await service.embed_all_stale(cast(AsyncSession, _Session()), provider)

    assert embedded == 1
    assert memory.targets == ["job", "candidate"]
