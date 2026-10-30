import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send

from app.core import errors as errors_module
from app.core import middleware as middleware_module
from app.core.errors import ConflictError, UnhandledErrorMiddleware
from app.main import create_app

ORIGIN = "http://localhost:5180"
EXPECTED_BODY = {
    "error": {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "details": {},
    }
}


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.calls.append(("info", event, fields))

    def exception(self, event: str, **fields: Any) -> None:
        self.calls.append(("exception", event, fields))


async def _raise_runtime_error() -> None:
    raise RuntimeError("secret value")


async def _raise_conflict() -> None:
    raise ConflictError("Already there.")


async def _stream_then_fail() -> StreamingResponse:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"first"
        raise RuntimeError("stream broke")

    return StreamingResponse(chunks())


@pytest.fixture
def boom_app() -> FastAPI:
    app = create_app()
    app.add_api_route("/boom", _raise_runtime_error)
    app.add_api_route("/conflict", _raise_conflict)
    app.add_api_route("/stream", _stream_then_fail)
    return app


@pytest.fixture
async def boom_client(boom_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=boom_app), base_url="http://test") as ac:
        yield ac


async def test_unexpected_error_returns_the_standard_body_without_the_message(
    boom_client: AsyncClient,
) -> None:
    response = await boom_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == EXPECTED_BODY
    assert "secret value" not in response.text


async def test_the_500_echoes_the_request_id(boom_client: AsyncClient) -> None:
    response = await boom_client.get("/boom", headers={"X-Request-ID": "abc"})

    assert response.headers["x-request-id"] == "abc"


async def test_the_500_gets_a_generated_request_id_when_none_is_sent(
    boom_client: AsyncClient,
) -> None:
    response = await boom_client.get("/boom")

    assert len(response.headers["x-request-id"]) == 36


async def test_the_500_carries_cors_headers_for_an_allowed_origin(
    boom_client: AsyncClient,
) -> None:
    response = await boom_client.get("/boom", headers={"Origin": ORIGIN})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_the_500_is_logged_as_a_completed_request(
    boom_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _RecordingLogger()
    monkeypatch.setattr(middleware_module, "logger", stub)
    monkeypatch.setattr(errors_module, "logger", stub)

    await boom_client.get("/boom")

    completed = [fields for _, event, fields in stub.calls if event == "request_completed"]
    assert len(completed) == 1
    assert completed[0]["status_code"] == 500
    assert completed[0]["path"] == "/boom"
    unhandled = [fields for _, event, fields in stub.calls if event == "unhandled_error"]
    assert unhandled == [{"error_type": "RuntimeError"}]


async def test_expected_errors_keep_their_own_status_and_code(boom_client: AsyncClient) -> None:
    response = await boom_client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_a_413_still_carries_cors_headers(boom_client: AsyncClient) -> None:
    response = await boom_client.post(
        "/boom", content=b"x" * (70 * 1024), headers={"Origin": ORIGIN}
    )

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == ORIGIN


async def test_an_error_after_the_response_started_is_raised_and_logged(
    boom_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _RecordingLogger()
    monkeypatch.setattr(errors_module, "logger", stub)

    with pytest.raises(RuntimeError, match="stream broke"):
        await boom_client.get("/stream")

    assert [event for _, event, _ in stub.calls] == ["unhandled_error"]


async def test_cancellation_is_not_turned_into_a_500() -> None:
    async def cancelled_app(scope: Scope, receive: Receive, send: Send) -> None:
        raise asyncio.CancelledError

    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = UnhandledErrorMiddleware(cancelled_app)

    with pytest.raises(asyncio.CancelledError):
        await middleware({"type": "http"}, receive, send)

    assert sent == []
