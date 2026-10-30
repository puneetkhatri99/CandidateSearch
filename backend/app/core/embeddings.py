"""The OpenAI embedding provider (official SDK) and its process-wide slot.

Callers send only redacted search documents here. Nothing in this module logs input text.
"""

import math
from dataclasses import dataclass

import httpx2
import openai

from app.core.config import OPENAI_BASE_URL, Settings, get_settings

# About 6,000 tokens of typical English text, under the model's 8,191-token input limit.
MAX_INPUT_CHARACTERS = 24_000
_HTTP_REQUEST_TIMEOUT = 408
_HTTP_CONFLICT = 409
# Bounded by the integer column the usage event is stored in.
_MAX_BILLED_TOKENS = 2**31


class EmbeddingError(Exception):
    """Base for provider failures. `status_code` is set when the provider answered."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TransientEmbeddingError(EmbeddingError):
    """Worth retrying: rate limits, 5xx, network and timeout (after the SDK's own retries)."""


class PermanentEmbeddingError(EmbeddingError):
    """Retrying cannot help: bad input, bad credentials, malformed responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        billed_tokens: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        # Set when the provider answered 200 with a usage block but the body was unusable: the
        # request was still billed, so the spend meter must record these tokens.
        self.billed_tokens = billed_tokens


class EmbeddingConfigurationError(Exception):
    """The provider cannot be built (for example, a missing API key)."""


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    total_tokens: int

    def billed_tokens(self) -> tuple[int, int]:
        """(input, output) tokens, the shape ai_usage.metered_call's `tokens_of` expects."""
        return self.total_tokens, 0


def truncate_text(text: str) -> str:
    return text[:MAX_INPUT_CHARACTERS]


def _map_sdk_error(exc: openai.OpenAIError) -> EmbeddingError:
    """Translate an SDK error into ours; its message can hold response text, so it is dropped."""
    if isinstance(exc, openai.APIConnectionError):
        return TransientEmbeddingError(type(exc).__name__)
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        if isinstance(exc, openai.RateLimitError | openai.InternalServerError) or status in (
            _HTTP_REQUEST_TIMEOUT,
            _HTTP_CONFLICT,
        ):
            return TransientEmbeddingError("provider unavailable", status_code=status)
        return PermanentEmbeddingError("provider rejected the request", status_code=status)
    return PermanentEmbeddingError(type(exc).__name__)


class OpenAIEmbeddingProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        dimensions: int,
        timeout_seconds: float,
        max_retries: int,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        # The SDK retries connection errors, timeouts, 408/409/429 and 5xx with backoff and
        # honours Retry-After. All attempts happen inside one embed_documents call, so they
        # stay inside one metered call: never add a retry outside it.
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=OPENAI_BASE_URL,
            max_retries=max_retries,
            timeout=timeout_seconds,
            http_client=http_client,
        )

    async def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
        try:
            response = await self._client.embeddings.create(
                model=self.model_name,
                input=[truncate_text(text) for text in texts],
                dimensions=self.dimensions,
                encoding_format="float",
            )
        except openai.OpenAIError as exc:
            raise _map_sdk_error(exc) from exc
        except ValueError as exc:
            # A 200 whose body is not JSON escapes the SDK as a raw json.JSONDecodeError.
            raise PermanentEmbeddingError("malformed provider response") from exc
        # The cost is logged once, exactly, by ai_usage.metered_call.
        return self._parse(response, expected=len(texts))

    async def aclose(self) -> None:
        await self._client.close()

    def _parse(
        self, response: openai.types.CreateEmbeddingResponse, *, expected: int
    ) -> EmbeddingBatch:
        billed_tokens: int | None = None
        try:
            total_tokens = int(response.usage.total_tokens)
            if 0 <= total_tokens < _MAX_BILLED_TOKENS:
                billed_tokens = total_tokens
            items = sorted(response.data, key=lambda item: item.index)
            vectors = [[float(x) for x in item.embedding] for item in items]
        except (AttributeError, TypeError, ValueError, KeyError, OverflowError) as exc:
            # The SDK builds models without strict validation, so a missing field only shows up
            # when it is read. OverflowError: Python's JSON parser accepts Infinity.
            raise PermanentEmbeddingError(
                "malformed provider response", billed_tokens=billed_tokens
            ) from exc
        if len(vectors) != expected or any(len(v) != self.dimensions for v in vectors):
            raise PermanentEmbeddingError(
                "provider returned unexpected vector shapes", billed_tokens=billed_tokens
            )
        # Python's JSON parser accepts NaN/Infinity, which Postgres would reject at write time.
        if not all(math.isfinite(x) for vector in vectors for x in vector):
            raise PermanentEmbeddingError(
                "provider returned non-finite vector values", billed_tokens=billed_tokens
            )
        return EmbeddingBatch(vectors=vectors, total_tokens=total_tokens)


def build_embedding_provider(
    settings: Settings, *, http_client: httpx2.AsyncClient | None = None
) -> OpenAIEmbeddingProvider:
    api_key = settings.usable_openai_api_key()
    if api_key is None:
        raise EmbeddingConfigurationError("Embedding requires a real OPENAI_API_KEY to be set.")
    return OpenAIEmbeddingProvider(
        api_key=api_key,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
        http_client=http_client,
    )


# The one injection seam: maintenance, the CLI and services get the provider only through here.
_installed_provider: OpenAIEmbeddingProvider | None = None


def get_embedding_provider() -> OpenAIEmbeddingProvider:
    global _installed_provider
    if _installed_provider is None:
        _installed_provider = build_embedding_provider(get_settings())
    return _installed_provider


def use_embedding_provider(provider: OpenAIEmbeddingProvider | None) -> None:
    """Install a provider (tests) or clear the slot, without closing what was there."""
    global _installed_provider
    _installed_provider = provider


async def close_embedding_provider() -> None:
    global _installed_provider
    provider, _installed_provider = _installed_provider, None
    if provider is not None:
        await provider.aclose()
