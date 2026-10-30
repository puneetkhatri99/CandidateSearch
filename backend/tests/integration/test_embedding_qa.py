"""QA checks for embedding: the retry schedule, no API key, the CLI, and the network guard."""

import uuid
from typing import Any

import httpx
import httpx2
import openai
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from app.cli import main as cli_main
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.embeddings import (
    OpenAIEmbeddingProvider,
    get_embedding_provider,
    use_embedding_provider,
)
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import CANDIDATES, embed_stale
from tests.openai_mock import OpenAIEmbeddingsMock

PUBLIC_URL = "/api/v1/candidates"


async def _seed(**overrides: Any) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        created = await create_candidate(
            session,
            CandidateCreate.model_validate(valid_candidate_payload(**overrides)),
            consent_version="test",
        )
    return created.id


async def _embed() -> int:
    async with get_sessionmaker()() as session:
        outcome = await embed_stale(session, get_embedding_provider(), CANDIDATES)
    return outcome.embedded + outcome.failed


async def _age_failures(seconds: int) -> None:
    """Move every failure `seconds` further into the past."""
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            text(
                "UPDATE embedding_failures SET updated_at = updated_at - make_interval(secs => :s)"
            ),
            {"s": seconds},
        )


async def test_a_temporary_failure_is_retried_after_30s_2min_8min_32min_then_given_up(
    openai_mock: OpenAIEmbeddingsMock,
) -> None:
    await _seed()
    for attempt, delay in enumerate((30, 120, 480, 1920), start=1):
        openai_mock.queue_status(503)
        assert await _embed() == 1, f"attempt {attempt} should run"
        # Not due yet just before the delay ends, due right after.
        await _age_failures(delay - 5)
        assert await _embed() == 0
        await _age_failures(10)
    openai_mock.queue_status(503)
    assert await _embed() == 1  # the 5th attempt
    await _age_failures(100_000)
    assert await _embed() == 0  # given up until the text changes
    assert len(openai_mock.requests) == 5


async def test_a_temporary_failure_succeeds_on_retry(openai_mock: OpenAIEmbeddingsMock) -> None:
    await _seed()
    openai_mock.queue_status(503)
    await _embed()
    await _age_failures(31)

    async with get_sessionmaker()() as session:
        outcome = await embed_stale(session, get_embedding_provider(), CANDIDATES)

    assert outcome.embedded == 1
    async with get_sessionmaker()() as session, session.begin():
        assert await session.scalar(text("SELECT count(*) FROM embedding_failures")) == 0


class _RecordingLogger:
    """Stands in for app.cli's logger: structlog caches loggers, so capture_logs is flaky."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.entries.append((event, fields))

    error = info


@pytest.fixture
async def _engine_not_bound_to_a_loop() -> None:
    # Sync tests run the CLI on its own event loop; pooled connections must not leak into it.
    await get_engine().dispose()


async def test_saves_succeed_when_no_api_key_is_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_embedding_provider(None)
    monkeypatch.setattr(get_settings(), "openai_api_key", None)

    response = await client.post(PUBLIC_URL, json=valid_candidate_payload())

    assert response.status_code == 201, response.text


def test_backfill_logs_embedding_not_configured_for_a_blank_and_a_placeholder_key(
    _engine_not_bound_to_a_loop: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("", "sk-CHANGE_ME"):
        use_embedding_provider(None)
        monkeypatch.setattr(get_settings(), "openai_api_key", SecretStr(key))
        monkeypatch.setattr("sys.argv", ["app.cli", "embed-backfill"])
        monkeypatch.setattr("app.cli.configure_logging", lambda _: None)

        recorder = _RecordingLogger()
        monkeypatch.setattr("app.cli.logger", recorder)

        with pytest.raises(SystemExit) as raised:
            cli_main()

        assert raised.value.code == 1
        assert [event for event, _ in recorder.entries] == ["embedding_not_configured"]


@pytest.fixture
async def seeded_candidate() -> uuid.UUID:
    candidate_id = await _seed()
    await get_engine().dispose()  # the sync CLI test below runs on its own event loop
    return candidate_id


def test_backfill_embeds_everything_and_logs_the_counts(
    seeded_candidate: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["app.cli", "embed-backfill"])
    monkeypatch.setattr("app.cli.configure_logging", lambda _: None)
    recorder = _RecordingLogger()
    monkeypatch.setattr("app.cli.logger", recorder)

    cli_main()

    done = {f["target"]: f for event, f in recorder.entries if event == "embed_backfill_completed"}
    # Jobs first, like the background task.
    assert list(done) == ["job", "candidate"]
    # The cost itself is recorded per call by ai_usage.metered_call (test_ai_usage_embeddings).
    assert (done["candidate"]["embedded"], done["candidate"]["failed"]) == (1, 0)
    assert done["candidate"]["blocked"] == 0


# --- The network guard and the environment ---------------------------------------------------


def test_the_tests_run_with_the_dummy_key_and_the_test_database_never_the_env_file() -> None:
    settings = get_settings()

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test-not-a-real-key"
    assert str(settings.database_url).rsplit("/", 1)[1].endswith("_test")


async def test_a_hostile_openai_base_url_in_the_environment_cannot_redirect_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://attacker.example/v1")
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test-not-a-real-key",
        model_name="text-embedding-3-small",
        dimensions=1536,
        timeout_seconds=1,
        max_retries=0,
    )
    try:
        assert provider._client.base_url.host == "api.openai.com"
        with pytest.raises(pytest.fail.Exception, match="Test tried to reach the network"):
            await provider.embed_documents(["x"])
    finally:
        await provider.aclose()


async def test_the_guard_stops_a_plain_sdk_client_built_by_a_careless_test() -> None:
    client = openai.AsyncOpenAI(api_key="sk-test-not-a-real-key", max_retries=3)
    try:
        with pytest.raises(pytest.fail.Exception, match=r"api\.openai\.com"):
            await client.embeddings.create(model="text-embedding-3-small", input=["x"])
    finally:
        await client.close()


async def test_the_guard_stops_every_httpx_flavour_that_could_reach_the_openai_host() -> None:
    url = "https://api.openai.com/v1/embeddings"
    async with httpx2.AsyncClient() as async_client:
        with pytest.raises(pytest.fail.Exception):
            await async_client.post(url, json={})
    async with httpx.AsyncClient() as legacy_async_client:
        with pytest.raises(pytest.fail.Exception):
            await legacy_async_client.post(url, json={})
    with pytest.raises(pytest.fail.Exception):
        httpx2.Client().post(url, json={})
    with pytest.raises(pytest.fail.Exception):
        httpx.Client().post(url, json={})
