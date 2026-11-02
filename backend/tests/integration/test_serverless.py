"""The one-server Vercel setup: embed on save, the cron route, the frontend served by the API."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app import main
from app import maintenance as app_maintenance
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings.models import CandidateEmbedding
from tests.integration.conftest import create_job

CANDIDATES = "/api/v1/admin/candidates"
CRON = "/api/v1/internal/maintenance"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(get_settings(), "embed_on_save", True)
    return main.create_app()


async def _embedded_candidates() -> int:
    async with get_sessionmaker()() as session:
        return await session.scalar(select(func.count()).select_from(CandidateEmbedding)) or 0


async def test_a_candidate_save_is_embedded_before_the_answer(admin_client: AsyncClient) -> None:
    payload = valid_candidate_payload()
    del payload["consent"]  # staff confirm consent instead
    response = await admin_client.post(CANDIDATES, json={**payload, "consent_confirmed": True})

    assert response.status_code == 201, response.text
    # No background loop on Vercel: the request itself did it.
    assert await _embedded_candidates() == 1


async def test_only_successful_candidate_and_job_writes_embed(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[None] = []

    async def record() -> None:
        calls.append(None)

    monkeypatch.setattr(app_maintenance, "embed_stale_now", record)

    await admin_client.get(CANDIDATES)
    assert calls == []
    refused = await admin_client.post(CANDIDATES, json={"consent_confirmed": True})
    assert refused.status_code == 422
    assert calls == []
    await create_job(admin_client)
    assert len(calls) == 1


async def test_without_the_setting_saves_do_not_embed_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "embed_on_save", False)
    app = main.create_app()
    assert not any(
        getattr(m.kwargs.get("dispatch"), "__name__", "") == "embed_after_saves"
        for m in app.user_middleware
    )


async def test_the_cron_route_hides_without_the_secret(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cron_secret", None)
    assert (await client.get(CRON, headers={"Authorization": "Bearer "})).status_code == 404

    monkeypatch.setattr(get_settings(), "cron_secret", SecretStr("right-secret"))
    assert (await client.get(CRON)).status_code == 404
    assert (await client.get(CRON, headers={"Authorization": "Bearer wrong"})).status_code == 404


async def test_the_cron_route_runs_every_task_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cron_secret", SecretStr("right-secret"))
    runs: list[bool] = []

    async def fake_run(tasks: object, *, once: bool = False) -> None:
        runs.append(once)

    monkeypatch.setattr(app_maintenance, "run_maintenance", fake_run)

    response = await client.get(CRON, headers={"Authorization": "Bearer right-secret"})

    assert response.status_code == 200
    assert runs == [True]


async def test_the_api_serves_the_built_frontend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    app = main.create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/admin/candidates", headers={"Accept": "text/html"})
        asset = await client.get("/assets/app.js")
        api = await client.get("/api/v1/auth/me")

    assert page.status_code == 200 and "<title>app</title>" in page.text
    assert asset.status_code == 200 and asset.text == "console.log(1)"
    # API routes always win, with the usual JSON error body.
    assert api.status_code == 401 and api.json()["error"]["code"]


def test_uploads_fit_under_vercels_body_limit() -> None:
    # Vercel refuses request bodies over 4.5 MB before they reach the app.
    assert get_settings().max_resume_bytes <= 4_500_000
