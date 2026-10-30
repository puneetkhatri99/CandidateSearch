import logging
import math

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import OPENAI_BASE_URL, Settings, get_settings
from app.core.embeddings import (
    MAX_INPUT_CHARACTERS,
    EmbeddingConfigurationError,
    OpenAIEmbeddingProvider,
    PermanentEmbeddingError,
    TransientEmbeddingError,
    build_embedding_provider,
    close_embedding_provider,
    get_embedding_provider,
    use_embedding_provider,
)
from app.core.errors import describe_error
from app.core.logging import configure_logging
from tests.openai_mock import OpenAIEmbeddingsMock, OpenAIProviderFactory, deterministic_vector

DIMENSIONS = 4
_ERROR_BODY_ECHO = "mocked failure"


async def test_provider_returns_vectors_in_input_order_with_the_billed_tokens(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    provider = openai_provider(dimensions=DIMENSIONS)

    batch = await provider.embed_documents(["a", "b", "c"])

    assert batch.vectors == [deterministic_vector(text, DIMENSIONS) for text in "abc"]
    assert batch.total_tokens == 3
    payload = openai_mock.payloads[0]
    assert payload["model"] == "text-embedding-3-small"
    assert payload["dimensions"] == DIMENSIONS
    assert payload["input"] == ["a", "b", "c"]


async def test_provider_orders_by_response_index(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    data = [
        {"object": "embedding", "index": 1, "embedding": [1.0] * DIMENSIONS},
        {"object": "embedding", "index": 0, "embedding": [0.0] * DIMENSIONS},
    ]
    openai_mock.queue_body({"object": "list", "data": data, "usage": {"total_tokens": 2}})

    batch = await openai_provider(dimensions=DIMENSIONS).embed_documents(["first", "second"])

    assert batch.vectors[0] == [0.0] * DIMENSIONS


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503])
async def test_transient_statuses_map_to_transient_errors_with_the_status(
    status: int, openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    openai_mock.queue_status(status)

    with pytest.raises(TransientEmbeddingError) as raised:
        await openai_provider().embed_documents(["text"])

    assert raised.value.status_code == status
    assert len(openai_mock.requests) == 1


@pytest.mark.parametrize(
    "error",
    [httpx2.ConnectError("c"), httpx2.ConnectTimeout("t"), httpx2.ReadTimeout("t")],
)
async def test_network_errors_map_to_transient_errors_without_a_status(
    error: Exception, openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    openai_mock.queue_exception(error)

    with pytest.raises(TransientEmbeddingError) as raised:
        await openai_provider().embed_documents(["text"])

    assert raised.value.status_code is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_map_to_permanent_errors_with_the_status(
    status: int, openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    openai_mock.queue_status(status)

    with pytest.raises(PermanentEmbeddingError) as raised:
        await openai_provider().embed_documents(["text"])

    assert raised.value.status_code == status
    # The provider's error body can echo input, so it must not reach the exception message.
    assert _ERROR_BODY_ECHO not in str(raised.value)


async def test_one_call_absorbs_the_sdk_retry_of_a_transient_failure(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    # retry-after-ms keeps the SDK's backoff short; it is honoured like Retry-After.
    openai_mock.queue_status(503, headers={"retry-after-ms": "1"})

    batch = await openai_provider(max_retries=1).embed_documents(["text"])

    assert len(batch.vectors) == 1
    assert len(openai_mock.requests) == 2


async def test_transient_error_is_raised_only_after_the_sdk_used_its_retries(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    for _ in range(2):
        openai_mock.queue_status(503, headers={"retry-after-ms": "1"})

    with pytest.raises(TransientEmbeddingError):
        await openai_provider(max_retries=1).embed_documents(["text"])

    assert len(openai_mock.requests) == 2


@pytest.mark.parametrize(
    "body",
    [
        {"object": "list", "data": [], "usage": {"total_tokens": 1}},
        {
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": [1.0]}],
            "usage": {"total_tokens": 1},
        },
        {"unexpected": True},
    ],
)
async def test_malformed_or_wrong_shape_response_is_permanent(
    body: dict[str, object],
    openai_mock: OpenAIEmbeddingsMock,
    openai_provider: OpenAIProviderFactory,
) -> None:
    openai_mock.queue_body(body)

    with pytest.raises(PermanentEmbeddingError):
        await openai_provider(dimensions=DIMENSIONS).embed_documents(["text"])


async def test_unusable_response_with_a_usage_block_carries_the_billed_tokens(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    provider = openai_provider(dimensions=DIMENSIONS)
    ragged = {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.5]}],
        "usage": {"total_tokens": 42},
    }
    openai_mock.queue_body(ragged)
    with pytest.raises(PermanentEmbeddingError) as shape_error:
        await provider.embed_documents(["text"])
    assert shape_error.value.billed_tokens == 42

    openai_mock.queue_body({"object": "list", "data": "nope", "usage": {"total_tokens": 9}})
    with pytest.raises(PermanentEmbeddingError) as malformed_error:
        await provider.embed_documents(["text"])
    assert malformed_error.value.billed_tokens == 9


async def test_unusable_response_without_a_usage_block_has_no_billed_tokens(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    openai_mock.queue_body({"object": "list", "data": []})

    with pytest.raises(PermanentEmbeddingError) as error:
        await openai_provider().embed_documents(["text"])
    assert error.value.billed_tokens is None


async def test_non_json_response_is_permanent(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    openai_mock.queue_body("<html>")

    with pytest.raises(PermanentEmbeddingError):
        await openai_provider().embed_documents(["text"])


async def test_inputs_are_truncated_before_sending(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    await openai_provider(dimensions=DIMENSIONS).embed_documents(
        ["x" * (MAX_INPUT_CHARACTERS + 500), "short"]
    )

    assert len(openai_mock.requests[0][0]) == MAX_INPUT_CHARACTERS
    assert openai_mock.requests[0][1] == "short"


def test_deterministic_vector_is_unit_length_and_distinct_per_text() -> None:
    alpha, beta = deterministic_vector("alpha"), deterministic_vector("beta")

    assert alpha == deterministic_vector("alpha")
    assert alpha != beta
    assert len(alpha) == 1536
    assert math.isclose(sum(v * v for v in alpha), 1.0, rel_tol=1e-9)


def test_factory_requires_api_key() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql+asyncpg://u:p@localhost/db", openai_api_key=None
    )

    with pytest.raises(EmbeddingConfigurationError):
        build_embedding_provider(settings)


async def test_factory_builds_the_provider_with_the_configured_client_options() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://u:p@localhost/db",
            "openai_api_key": SecretStr("sk-x"),
            "embedding_max_retries": 4,
            "embedding_timeout_seconds": 12,
        }
    )

    provider = build_embedding_provider(settings)

    try:
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider.dimensions == 1536
        assert provider._client.max_retries == 4
        assert provider._client.timeout == 12
        # Explicit, so an OPENAI_BASE_URL in the environment cannot redirect candidate text.
        assert str(provider._client.base_url).rstrip("/") == OPENAI_BASE_URL
    finally:
        await provider.aclose()


async def test_installed_provider_is_what_get_embedding_provider_returns(
    openai_provider: OpenAIProviderFactory,
) -> None:
    installed = openai_provider()

    use_embedding_provider(installed)

    assert get_embedding_provider() is installed


async def test_get_embedding_provider_builds_from_settings_once_and_keeps_it() -> None:
    use_embedding_provider(None)

    first = get_embedding_provider()
    try:
        assert get_embedding_provider() is first
    finally:
        await close_embedding_provider()


async def test_close_embedding_provider_closes_the_client_and_clears_the_slot() -> None:
    use_embedding_provider(None)
    provider = get_embedding_provider()

    await close_embedding_provider()

    assert provider._client.is_closed()
    assert get_embedding_provider() is not provider
    await close_embedding_provider()


async def test_close_embedding_provider_without_a_provider_is_a_no_op() -> None:
    use_embedding_provider(None)

    await close_embedding_provider()


def test_api_key_is_not_exposed_in_settings_repr() -> None:
    settings = Settings.model_validate(
        {"database_url": "postgresql+asyncpg://u:p@localhost/db", "openai_api_key": "sk-secret"}
    )

    assert "sk-secret" not in repr(settings)


def test_sdk_loggers_are_pinned_above_debug_so_input_text_is_never_logged() -> None:
    configure_logging(get_settings())

    for name in ("openai", "httpx", "httpx2"):
        assert logging.getLogger(name).level == logging.WARNING


def test_describe_error_contains_class_and_status_only() -> None:
    assert describe_error(TransientEmbeddingError("body text", status_code=429)) == (
        "TransientEmbeddingError status=429"
    )
    assert describe_error(ValueError("secret")) == "ValueError"
