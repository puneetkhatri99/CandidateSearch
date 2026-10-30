"""QA probes for Phase 1b: sessions, CSRF, cursors, pagination, audit hygiene, latency."""

import base64
import json
import time
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.features.audit.models import AuditEvent
from app.features.auth.models import UserSession
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.models import Candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from tests.integration.conftest import FETCH_HEADERS, STAFF_PASSWORD, create_staff

URL = "/api/v1/admin/candidates"
LOGIN = "/api/v1/auth/login"


def _cursor(payload: Any) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def _seed(i: int, **overrides: Any) -> uuid.UUID:
    payload = valid_candidate_payload(
        full_name=f"Person {i:04d}", email=f"person{i}@example.com", **overrides
    )
    async with get_sessionmaker()() as session:
        created = await create_candidate(
            session, CandidateCreate.model_validate(payload), consent_version="test"
        )
    return created.id


# --- Sessions ---------------------------------------------------------------------------


async def test_copied_cookie_is_dead_after_logout(app: FastAPI) -> None:
    await create_staff("admin@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as a:
        r = await a.post(
            LOGIN,
            json={"email": "admin@example.com", "password": STAFF_PASSWORD},
            headers=FETCH_HEADERS,
        )
        token = r.cookies["session"] if "session" in r.cookies else next(iter(r.cookies.values()))
        name = next(iter(r.cookies.keys()))
        assert (await a.post("/api/v1/auth/logout", headers=FETCH_HEADERS)).status_code == 204
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as attacker:
        attacker.cookies.set(name, token)
        assert (await attacker.get(URL)).status_code == 401
        assert (await attacker.get("/api/v1/auth/me")).status_code == 401


async def test_logout_without_csrf_header_keeps_session(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.post("/api/v1/auth/logout", headers={"X-Requested-With": ""})

    assert response.status_code == 403
    assert (await admin_client.get("/api/v1/auth/me")).status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 1


async def test_each_login_issues_a_fresh_token_ignoring_presented_cookie(
    app: FastAPI, db_session: AsyncSession
) -> None:
    await create_staff("admin@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.cookies.set("session", "attacker-chosen-token")
        r = await c.post(
            LOGIN,
            json={"email": "admin@example.com", "password": STAFF_PASSWORD},
            headers=FETCH_HEADERS,
        )
        assert r.status_code == 200
        assert "attacker-chosen-token" not in r.headers["set-cookie"]


async def test_wrong_csrf_header_value_is_rejected_on_every_write(
    admin_client: AsyncClient,
) -> None:
    cid = await _seed(1)
    bad = {"X-Requested-With": "XMLHttpRequest"}
    for method, path in [
        ("POST", URL),
        ("PUT", f"{URL}/{cid}"),
        ("DELETE", f"{URL}/{cid}"),
        ("POST", "/api/v1/auth/logout"),
    ]:
        r = await admin_client.request(method, path, headers=bad, json={})
        assert r.status_code == 403, (method, path, r.text)
        assert r.json()["error"]["code"] == "csrf_failed"


async def test_login_wrong_csrf_value_rejected(client: AsyncClient) -> None:
    await create_staff("admin@example.com")
    r = await client.post(
        LOGIN,
        json={"email": "admin@example.com", "password": STAFF_PASSWORD},
        headers={"X-Requested-With": "nope"},
    )
    assert r.status_code == 403
    assert "set-cookie" not in r.headers


# --- Cursors ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!not-base64!!!",
        _cursor([1, 2]),
        _cursor("str"),
        _cursor({}),
        _cursor({"key": "2020-01-01T00:00:00", "id": str(uuid.uuid4())}),
        _cursor({"key": "garbage", "id": str(uuid.uuid4())}),
        _cursor({"key": 5, "id": str(uuid.uuid4())}),
        _cursor({"key": "2020-01-01T00:00:00+00:00", "id": "not-a-uuid"}),
        _cursor({"key": "0001-01-01T00:00:00+00:00", "id": str(uuid.uuid4())}),
        _cursor({"key": "9999-12-31T23:59:59+23:59", "id": str(uuid.uuid4())}),
        _cursor({"key": "9999-12-31T23:59:59.999999-23:59", "id": str(uuid.uuid4())}),
        _cursor({"key": "0001-01-01T00:00:00+23:59", "id": str(uuid.uuid4())}),
    ],
)
async def test_tampered_cursor_is_400_not_a_server_error(
    admin_client: AsyncClient, cursor: str
) -> None:
    response = await admin_client.get(URL, params={"cursor": cursor})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_cursor"


# --- Pagination -------------------------------------------------------------------------


async def _walk(client: AsyncClient, limit: int, on_page: Any = None) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    page_no = 0
    while True:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get(URL, params=params)).json()
        seen.extend(item["id"] for item in body["items"])
        page_no += 1
        if on_page:
            await on_page(page_no)
        cursor = body["next_cursor"]
        if not cursor:
            return seen


async def test_newest_pagination_is_stable_while_inserting(admin_client: AsyncClient) -> None:
    original = {str(await _seed(i)) for i in range(12)}

    async def insert(page_no: int) -> None:
        await _seed(100 + page_no)

    seen = await _walk(admin_client, 5, insert)

    assert len(seen) == len(set(seen)), "duplicate rows across pages"
    assert original <= set(seen), "an existing row was skipped"


# --- Search input -----------------------------------------------------------------------


async def test_hostile_filter_values(admin_client: AsyncClient) -> None:
    await _seed(1)
    for city in ["%", "_", "\\", "'; DROP TABLE candidates;--", "ß İ ǅ", "   "]:
        r = await admin_client.get(URL, params={"city": city, "skill": city})
        assert r.status_code in {200, 422}, (city, r.text)
    assert (await admin_client.get(URL, params={"city": "\u0000"})).status_code == 422
    assert (await admin_client.get(URL)).json()["items"], "table must still exist"


async def test_limit_bounds(admin_client: AsyncClient) -> None:
    for limit in ["0", "-1", "101", "abc"]:
        assert (await admin_client.get(URL, params={"limit": limit})).status_code == 422


async def test_search_latency_with_1000_candidates(admin_client: AsyncClient) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            text(
                """
                INSERT INTO candidates (id, full_name, email, city, country_code, headline,
                  years_experience, skills, summary, desired_roles, work_modes,
                  open_to_relocation, source, consent_given_at, consent_version,
                  search_document, version, created_at, updated_at)
                SELECT gen_random_uuid(), 'Person ' || g, 'p' || g || '@example.com', 'Pune', 'IN',
                  'Backend Engineer', (g % 20), ARRAY['python','fastapi'], 'summary text here',
                  ARRAY[]::text[], ARRAY['remote'], false, 'synthetic', now(), 'test',
                  'doc', 1, now(), now()
                FROM generate_series(1, 1000) g
                """
            )
        )
    assert await _count() >= 1000
    timings: list[tuple[dict[str, Any], float]] = []
    queries: list[dict[str, Any]] = [
        {"city": "pune"},
        {"skill": "python", "city": "Pune", "country": "IN", "min_years": 3},
        {"skill": "fastapi", "limit": 100},
    ]
    for params in queries:
        start = time.perf_counter()
        r = await admin_client.get(URL, params=params)
        timings.append((params, time.perf_counter() - start))
        assert r.status_code == 200, r.text
    assert all(t < 0.3 for _, t in timings), timings


async def _count() -> int:
    async with get_sessionmaker()() as session:
        return int(await session.scalar(select(func.count()).select_from(Candidate)) or 0)


# --- Edit / audit -----------------------------------------------------------------------


async def test_put_rejects_unknown_and_consent_fields(admin_client: AsyncClient) -> None:
    cid = await _seed(1)
    detail = (await admin_client.get(f"{URL}/{cid}")).json()
    body = {
        k: detail[k]
        for k in detail
        if k
        not in {"id", "source", "created_at", "updated_at", "consent_given_at", "consent_version"}
    }
    assert (await admin_client.put(f"{URL}/{cid}", json=body)).status_code == 200
    for extra in ({"source": "admin"}, {"consent_version": "hax"}, {"id": str(uuid.uuid4())}):
        r = await admin_client.put(f"{URL}/{cid}", json={**body, **extra})
        assert r.status_code == 422, (extra, r.text)


async def test_audit_log_holds_no_personal_values(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = valid_candidate_payload(full_name="Zed Unique", email="zed.unique@example.com")
    payload["consent_confirmed"] = payload.pop("consent")
    created = await admin_client.post(URL, json=payload)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    detail = created.json()
    body = {
        k: detail[k]
        for k in detail
        if k
        not in {"id", "source", "created_at", "updated_at", "consent_given_at", "consent_version"}
    }
    body.update(full_name="Zed Renamed", email="zed.renamed@example.com", city="Springfield")
    assert (await admin_client.put(f"{URL}/{cid}", json=body)).status_code == 200
    await admin_client.get(f"{URL}/{cid}")
    assert (await admin_client.delete(f"{URL}/{cid}")).status_code == 204

    rows = (await db_session.scalars(select(AuditEvent))).all()
    blob = json.dumps(
        [{"d": r.details, "a": r.action, "t": r.entity_type, "i": r.ip} for r in rows]
    ).lower()
    for needle in ["zed", "unique", "renamed", "springfield", "@example.com", "asha", "bengaluru"]:
        assert needle not in blob, needle
    actions = sorted(r.action for r in rows if r.entity_type == "candidate")
    assert actions == ["candidate.create", "candidate.delete", "candidate.update", "candidate.view"]


async def test_delete_twice_and_gone_from_search(admin_client: AsyncClient) -> None:
    cid = await _seed(1)
    assert (await admin_client.delete(f"{URL}/{cid}")).status_code == 204
    assert (await admin_client.delete(f"{URL}/{cid}")).status_code == 404
    assert (await admin_client.get(URL)).json()["items"] == []
    assert (await admin_client.get(f"{URL}/{cid}")).status_code == 404


async def test_malformed_id_is_422_not_500(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(f"{URL}/not-a-uuid")).status_code == 422
    assert (await admin_client.delete(f"{URL}/not-a-uuid")).status_code == 422
