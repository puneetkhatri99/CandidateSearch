"""Embedding in the background: the maintenance runner inside the API, and what triggers a call."""

import asyncio
import signal
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import maintenance as app_maintenance
from app.core import maintenance
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.embeddings import get_embedding_provider, use_embedding_provider
from app.features.ai_usage.models import AiUsageEvent
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import embed_all_stale
from app.features.embeddings.models import CandidateEmbedding, JobEmbedding
from tests.integration.conftest import FETCH_HEADERS, create_job, create_staff, login
from tests.openai_mock import OpenAIEmbeddingsMock

ADMIN_URL = "/api/v1/admin/candidates"


async def _count(db_session: AsyncSession, model: Any) -> int:
    db_session.expire_all()
    return int(await db_session.scalar(select(func.count()).select_from(model)) or 0)


async def _wait_until(check: Callable[[], Awaitable[bool]], seconds: float = 10) -> None:
    started = time.monotonic()
    while not await check():
        assert time.monotonic() - started < seconds, "condition not reached in time"
        await asyncio.sleep(0.05)


@pytest.fixture
def background_on(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "maintenance_in_api", True)
    monkeypatch.setattr(settings, "embedding_poll_seconds", 0.05)


@asynccontextmanager
async def _signed_in(app: FastAPI) -> AsyncIterator[AsyncClient]:
    await create_staff("recruiter@example.com", "recruiter")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await login(client, "recruiter@example.com")
        yield client


async def test_with_only_the_api_running_new_candidates_and_jobs_get_embeddings(
    app: FastAPI, db_session: AsyncSession, background_on: None
) -> None:
    before = signal.getsignal(signal.SIGINT)
    async with app.router.lifespan_context(app), _signed_in(app) as client:
        assert signal.getsignal(signal.SIGINT) is before  # uvicorn owns the signals
        candidate = await client.post(
            "/api/v1/candidates", json=valid_candidate_payload(), headers=FETCH_HEADERS
        )
        assert candidate.status_code == 201
        await create_job(client)

        async def both_embedded() -> bool:
            return (
                await _count(db_session, JobEmbedding) == 1
                and await _count(db_session, CandidateEmbedding) == 1
            )

        await _wait_until(both_embedded)

    assert maintenance._handle is None
    statuses = list(await db_session.scalars(select(AiUsageEvent.status)))
    assert statuses and set(statuses) == {"succeeded"}


async def test_shutdown_waits_for_the_in_flight_call_and_records_it(
    app: FastAPI,
    db_session: AsyncSession,
    openai_mock: OpenAIEmbeddingsMock,
    background_on: None,
) -> None:
    started = asyncio.Event()

    async def slow_call(_: list[str]) -> None:
        started.set()
        await asyncio.sleep(0.5)

    openai_mock.on_request = slow_call
    async with app.router.lifespan_context(app), _signed_in(app) as client:
        await create_job(client)
        await asyncio.wait_for(started.wait(), timeout=10)
        # Leaving the lifespan now stops the runner while the OpenAI call is in flight.

    statuses = list(await db_session.scalars(select(AiUsageEvent.status)))
    assert statuses == ["succeeded"]
    assert await _count(db_session, JobEmbedding) == 1


async def test_the_setting_off_starts_nothing(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(get_settings(), "maintenance_in_api", False)

    async with app.router.lifespan_context(app):
        assert maintenance._handle is None
        async with _signed_in(app) as client:
            await create_job(client)
            await asyncio.sleep(0.3)

    assert await _count(db_session, JobEmbedding) == 0


@pytest.mark.parametrize("key", [None, "", "   ", "sk-CHANGE_ME"])
async def test_a_missing_or_placeholder_key_leaves_only_the_pruning_tasks(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    monkeypatch.setattr(get_settings(), "openai_api_key", None if key is None else SecretStr(key))
    use_embedding_provider(None)
    events: list[str] = []

    class Log:
        def warning(self, event: str, **_: Any) -> None:
            events.append(event)

    monkeypatch.setattr(app_maintenance, "logger", Log())

    names = [task.name for task in app_maintenance.maintenance_tasks()]

    assert "embeddings.embed_stale" not in names
    assert names  # pruning still runs
    assert events == ["embedding_disabled"]


async def test_with_a_key_embedding_runs_first() -> None:
    names = [task.name for task in app_maintenance.maintenance_tasks()]
    assert names[0] == "embeddings.embed_stale"


# --- Only changed embedded text costs a call -------------------------------------------------


_EDITABLE = (
    "full_name",
    "email",
    "phone",
    "city",
    "country_code",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "headline",
    "years_experience",
    "skills",
    "summary",
    "experiences",
    "educations",
    "desired_roles",
    "work_modes",
    "open_to_relocation",
    "notice_period_days",
    "version",
)


async def _embed() -> int:
    async with get_sessionmaker()() as session:
        return await embed_all_stale(session, get_embedding_provider())


async def _save(admin_client: AsyncClient, candidate_id: uuid.UUID, **changes: Any) -> None:
    detail = (await admin_client.get(f"{ADMIN_URL}/{candidate_id}")).json()
    body = {key: detail[key] for key in _EDITABLE} | changes
    response = await admin_client.put(f"{ADMIN_URL}/{candidate_id}", json=body)
    assert response.status_code == 200, response.text


@pytest.fixture
async def embedded_candidate(admin_client: AsyncClient) -> uuid.UUID:
    response = await admin_client.post(
        ADMIN_URL,
        json={
            **{k: v for k, v in valid_candidate_payload().items() if k != "consent"},
            "consent_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    assert await _embed() == 1
    return uuid.UUID(response.json()["id"])


async def test_an_identical_resave_makes_no_call(
    admin_client: AsyncClient, embedded_candidate: uuid.UUID, openai_mock: OpenAIEmbeddingsMock
) -> None:
    await _save(admin_client, embedded_candidate)
    assert await _embed() == 0
    assert len(openai_mock.requests) == 1


async def test_a_phone_change_makes_no_call_because_it_is_not_embedded(
    admin_client: AsyncClient, embedded_candidate: uuid.UUID, openai_mock: OpenAIEmbeddingsMock
) -> None:
    await _save(admin_client, embedded_candidate, phone="+44 20 7946 0999")
    assert await _embed() == 0
    assert len(openai_mock.requests) == 1


async def test_a_change_to_embedded_text_is_embedded_again(
    admin_client: AsyncClient, embedded_candidate: uuid.UUID, openai_mock: OpenAIEmbeddingsMock
) -> None:
    await _save(admin_client, embedded_candidate, headline="Staff platform engineer")
    assert await _embed() == 1
    assert len(openai_mock.requests) == 2
