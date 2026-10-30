"""Test data for OpenAI's HTTP layer: a transport handler that answers like /v1/embeddings.

The real `OpenAIEmbeddingProvider` and the real SDK run in tests; only the transport under the
SDK is replaced, so request building, response parsing, retries and error classes are real.
"""

import hashlib
import inspect
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx2

from app.core.embeddings import OpenAIEmbeddingProvider

_CHARACTERS_PER_TOKEN = 4

type _Queued = httpx2.Response | Exception


class OpenAIProviderFactory(Protocol):
    """Builds extra providers on the same mock: another model, dimensions or max_retries."""

    def __call__(
        self, *, model_name: str | None = None, dimensions: int | None = None, max_retries: int = 0
    ) -> OpenAIEmbeddingProvider: ...


def deterministic_vector(text: str, dimensions: int = 1536) -> list[float]:
    """A unit vector derived from the text: equal texts have cosine 1.0, different ones differ."""
    values: list[float] = []
    block = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{block}:{text}".encode()).digest()
        values.extend((byte - 127.5) / 127.5 for byte in digest)
        block += 1
    values = values[:dimensions]
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def estimate_tokens(texts: list[str]) -> int:
    return sum(math.ceil(len(text) / _CHARACTERS_PER_TOKEN) for text in texts)


def embeddings_body(
    texts: list[str], *, model: str = "text-embedding-3-small", dimensions: int = 1536
) -> dict[str, object]:
    tokens = estimate_tokens(texts)
    return {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "index": index,
                "embedding": deterministic_vector(text, dimensions),
            }
            for index, text in enumerate(texts)
        ],
        "model": model,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }


@dataclass
class OpenAIEmbeddingsMock:
    # Inputs of every HTTP request, in order (equals the provider-call count when max_retries=0).
    requests: list[list[str]] = field(default_factory=list)
    # The full JSON payload of every request, to assert on exactly what went over the wire.
    payloads: list[dict[str, object]] = field(default_factory=list)
    # Any request with an input containing this text is answered with HTTP 400.
    reject_containing: str | None = None
    # Runs after the request is recorded and before it is answered (set an event, block, ...).
    on_request: Callable[[list[str]], Awaitable[None] | None] | None = None
    _queue: list[_Queued] = field(default_factory=list)

    def queue_status(self, status: int, *, headers: dict[str, str] | None = None) -> None:
        body = {"error": {"message": "mocked failure", "type": "mock_error", "code": None}}
        self._queue.append(httpx2.Response(status, json=body, headers=headers))

    def queue_body(self, body: object, status: int = 200) -> None:
        """Answer the next request with this body; a str or bytes is sent as-is (not JSON)."""
        # json.dumps writes NaN/Infinity as bare tokens, like a misbehaving provider would.
        content = body if isinstance(body, str | bytes) else json.dumps(body)
        self._queue.append(
            httpx2.Response(status, content=content, headers={"content-type": "application/json"})
        )

    def queue_exception(self, exc: Exception) -> None:
        self._queue.append(exc)

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        texts: list[str] = payload["input"]
        self.requests.append(texts)
        self.payloads.append(payload)
        if self.on_request is not None:
            hook_result = self.on_request(texts)
            if inspect.isawaitable(hook_result):
                await hook_result
        if self._queue:
            queued = self._queue.pop(0)
            if isinstance(queued, Exception):
                raise queued
            return queued
        if self.reject_containing and any(self.reject_containing in text for text in texts):
            return httpx2.Response(
                400, json={"error": {"message": "mocked rejection", "type": "invalid_request"}}
            )
        return httpx2.Response(
            200,
            json=embeddings_body(
                texts, model=payload["model"], dimensions=payload.get("dimensions", 1536)
            ),
        )
