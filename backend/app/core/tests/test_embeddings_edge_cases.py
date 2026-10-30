"""QA edge cases for the embedding provider and configuration (HTTP is mocked, no network)."""

import pytest

from app.core.config import Settings, get_settings
from app.core.embeddings import (
    EmbeddingConfigurationError,
    PermanentEmbeddingError,
    build_embedding_provider,
    use_embedding_provider,
)
from tests.openai_mock import OpenAIEmbeddingsMock, OpenAIProviderFactory

DIMENSIONS = 4
_DATABASE_URL = "postgresql+asyncpg://u:p@localhost/db"


def _embedding(index: int, values: list[float]) -> dict[str, object]:
    return {"object": "embedding", "index": index, "embedding": values}


@pytest.mark.parametrize("returned", [1, 3])
async def test_vector_count_mismatch_is_permanent_and_not_retried(
    returned: int, openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    data = [_embedding(i, [0.1] * DIMENSIONS) for i in range(returned)]
    openai_mock.queue_body({"object": "list", "data": data, "usage": {"total_tokens": 3}})

    with pytest.raises(PermanentEmbeddingError):
        await openai_provider(dimensions=DIMENSIONS).embed_documents(["a", "b"])

    assert len(openai_mock.requests) == 1


async def test_ragged_dimensions_in_one_response_are_permanent(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    data = [_embedding(0, [0.1] * DIMENSIONS), _embedding(1, [0.1] * (DIMENSIONS + 1))]
    openai_mock.queue_body({"object": "list", "data": data, "usage": {"total_tokens": 2}})

    with pytest.raises(PermanentEmbeddingError):
        await openai_provider(dimensions=DIMENSIONS).embed_documents(["a", "b"])


async def test_request_never_contains_extra_fields_beyond_the_documents(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    await openai_provider(dimensions=DIMENSIONS).embed_documents(["only the redacted document"])

    payload = openai_mock.payloads[0]
    assert set(payload) == {"model", "input", "dimensions", "encoding_format"}
    assert payload["input"] == ["only the redacted document"]
    # Explicit, otherwise the SDK asks for base64 and decodes it.
    assert payload["encoding_format"] == "float"


@pytest.mark.parametrize("token", [float("nan"), float("inf"), float("-inf")])
async def test_non_finite_values_anywhere_in_a_response_are_permanent(
    token: float, openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    data = [_embedding(0, [0.1, 0.1, 0.1, token])]
    openai_mock.queue_body({"object": "list", "data": data, "usage": {"total_tokens": 1}})

    with pytest.raises(PermanentEmbeddingError) as raised:
        await openai_provider(dimensions=DIMENSIONS).embed_documents(["text"])

    assert raised.value.billed_tokens == 1


async def test_infinite_token_count_is_permanent_not_an_unhandled_overflow(
    openai_mock: OpenAIEmbeddingsMock, openai_provider: OpenAIProviderFactory
) -> None:
    data = [_embedding(0, [0.1] * DIMENSIONS)]
    openai_mock.queue_body(
        {"object": "list", "data": data, "usage": {"total_tokens": float("inf")}}
    )

    with pytest.raises(PermanentEmbeddingError) as raised:
        await openai_provider(dimensions=DIMENSIONS).embed_documents(["text"])

    assert raised.value.billed_tokens is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_api_key_is_a_configuration_error(blank: str) -> None:
    settings = Settings(_env_file=None, database_url=_DATABASE_URL, openai_api_key=blank)

    with pytest.raises(EmbeddingConfigurationError):
        build_embedding_provider(settings)


def test_placeholder_api_key_from_env_example_is_a_configuration_error() -> None:
    settings = Settings(_env_file=None, database_url=_DATABASE_URL, openai_api_key="sk-CHANGE_ME")

    with pytest.raises(EmbeddingConfigurationError):
        build_embedding_provider(settings)


async def test_api_key_is_stripped_before_use() -> None:
    settings = Settings(
        _env_file=None, database_url=_DATABASE_URL, openai_api_key="  sk-real-looking  "
    )

    provider = build_embedding_provider(settings)

    try:
        assert provider._client.api_key == "sk-real-looking"
    finally:
        await provider.aclose()


async def test_the_network_guard_fails_a_provider_that_would_use_a_real_transport() -> None:
    """The default SDK transport must never be reachable from a test, even by mistake."""
    use_embedding_provider(None)
    provider = build_embedding_provider(get_settings())

    try:
        with pytest.raises(pytest.fail.Exception, match="Test tried to reach the network"):
            await provider.embed_documents(["text"])
    finally:
        await provider.aclose()
