from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from app.core.db import get_session


class _FakeSession:
    def __init__(self, error: Exception | None = None, pgvector: bool = True) -> None:
        self._error = error
        self._pgvector = pgvector

    async def execute(self, *_: Any, **__: Any) -> None:
        if self._error:
            raise self._error

    async def scalar(self, *_: Any, **__: Any) -> bool:
        if self._error:
            raise self._error
        return self._pgvector


def _use_session(app: FastAPI, session: _FakeSession) -> None:
    async def override() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = override


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_liveness_echoes_request_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


async def test_readiness_ok_when_database_and_pgvector_are_up(
    app: FastAPI, client: AsyncClient
) -> None:
    _use_session(app, _FakeSession())

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": True, "pgvector": True}}


async def test_readiness_503_when_pgvector_missing(app: FastAPI, client: AsyncClient) -> None:
    _use_session(app, _FakeSession(pgvector=False))

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": True, "pgvector": False}


async def test_readiness_503_when_database_unreachable(app: FastAPI, client: AsyncClient) -> None:
    _use_session(app, _FakeSession(error=ConnectionRefusedError()))

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": False, "pgvector": False},
    }


async def test_unknown_route_uses_standard_error_body(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
