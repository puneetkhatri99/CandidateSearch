import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from dotenv import dotenv_values


def _test_database_url() -> str:
    """Tests always use a dedicated database, never the dev one.

    TEST_DATABASE_URL wins (CI); otherwise derive `<dev db name>_test` from backend/.env.
    """
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    dev_url = dotenv_values(Path(__file__).parent / ".env").get("DATABASE_URL")
    if dev_url:
        base, _, name = dev_url.rpartition("/")
        return f"{base}/{name}_test"
    return "postgresql+asyncpg://test:test@localhost:5432/test"


# Must run before any app import so settings pick these up.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = _test_database_url()
# A dummy key: the provider is real, its HTTP layer is mocked, and the .env key never loads.
os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"
# Tests never start background tasks (embedding, pruning); they call the functions directly.
os.environ["MAINTENANCE_IN_API"] = "false"
# The SDK reads these itself; they must not redirect requests or turn on input logging.
os.environ.pop("OPENAI_BASE_URL", None)
os.environ.pop("OPENAI_LOG", None)

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.embeddings import (
    OpenAIEmbeddingProvider,
    build_embedding_provider,
    close_embedding_provider,
    use_embedding_provider,
)
from app.main import create_app
from tests.openai_mock import OpenAIEmbeddingsMock, OpenAIProviderFactory


@pytest.fixture(scope="session", autouse=True)
def forbid_real_network() -> Iterator[None]:
    """Fail any test that uses a real HTTP transport.

    pytest.fail raises a BaseException, which the SDK's retry loop (it catches Exception)
    cannot turn into a connection error. MockTransport and ASGITransport are other classes.
    """

    def refuse(self: object, request: httpx.Request | httpx2.Request) -> None:
        pytest.fail(f"Test tried to reach the network: {request.method} {request.url}")

    patcher = pytest.MonkeyPatch()
    for module in (httpx2, httpx):
        patcher.setattr(module.AsyncHTTPTransport, "handle_async_request", refuse)
        patcher.setattr(module.HTTPTransport, "handle_request", refuse)
    yield
    patcher.undo()


@pytest.fixture(autouse=True)
async def openai_mock() -> AsyncIterator[OpenAIEmbeddingsMock]:
    """The real provider over a mocked OpenAI HTTP layer, installed as the process-wide one."""
    mock = OpenAIEmbeddingsMock()
    settings = get_settings().model_copy(update={"embedding_max_retries": 0})
    provider = build_embedding_provider(
        settings, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(mock.handler))
    )
    use_embedding_provider(provider)
    yield mock
    await close_embedding_provider()


@pytest.fixture
async def openai_provider(
    openai_mock: OpenAIEmbeddingsMock,
) -> AsyncIterator[OpenAIProviderFactory]:
    """Build extra providers on the same mock (another model, batch size or max_retries)."""
    created: list[OpenAIEmbeddingProvider] = []

    def make(
        *, model_name: str | None = None, dimensions: int | None = None, max_retries: int = 0
    ) -> OpenAIEmbeddingProvider:
        settings = get_settings()
        provider = OpenAIEmbeddingProvider(
            api_key="sk-test-not-a-real-key",
            model_name=model_name or settings.embedding_model,
            dimensions=dimensions or settings.embedding_dimensions,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=max_retries,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(openai_mock.handler)),
        )
        created.append(provider)
        return provider

    yield make
    for provider in created:
        await provider.aclose()


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
