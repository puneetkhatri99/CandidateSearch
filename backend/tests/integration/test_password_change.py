"""The forced password change guard and POST /auth/change-password."""

import re
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.features.audit.models import AuditEvent
from app.features.auth import create_user
from app.features.auth.models import User, UserSession
from tests.integration.conftest import FETCH_HEADERS, STAFF_PASSWORD, login, signed_in_client

CHANGE = "/api/v1/auth/change-password"
NEW_PASSWORD = "a-brand-new-password"
FLAGGED_EMAIL = "flagged@example.com"

# Routes that must keep working while a password change is pending, or are public by design.
PUBLIC_OR_EXEMPT = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/candidates"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/change-password"),
}


async def _create_flagged_recruiter() -> None:
    async with get_sessionmaker()() as session:
        await create_user(
            session,
            email=FLAGGED_EMAIL,
            full_name="Flagged Person",
            password=STAFF_PASSWORD,
            role="recruiter",
            must_change_password=True,
        )


async def _login_raw(client: AsyncClient, password: str) -> int:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": FLAGGED_EMAIL, "password": password},
        headers=FETCH_HEADERS,
    )
    return response.status_code


async def test_login_succeeds_for_a_flagged_user_and_reports_the_flag(client: AsyncClient) -> None:
    await _create_flagged_recruiter()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": FLAGGED_EMAIL, "password": STAFF_PASSWORD},
        headers=FETCH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True


async def test_every_guarded_route_refuses_a_flagged_user(
    app: FastAPI, client: AsyncClient
) -> None:
    """Enumerates the real routes, so a route added later is covered without editing this test."""
    await _create_flagged_recruiter()
    await login(client, FLAGGED_EMAIL)

    checked: list[tuple[str, str]] = []
    # The OpenAPI document lists every route, however FastAPI nests the routers internally.
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in sorted(m.upper() for m in operations):
            if (method, path) in PUBLIC_OR_EXEMPT:
                continue
            url = re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)
            body: dict[str, str] | None = {} if method in {"POST", "PUT", "PATCH"} else None
            response = await client.request(method, url, json=body)
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["error"]["code"] == "password_change_required", (method, path)
            checked.append((method, path))
    assert ("GET", "/api/v1/admin/candidates") in checked
    assert ("GET", "/api/v1/jobs") in checked
    assert ("GET", "/api/v1/admin/users") in checked
    assert any(path.startswith("/api/v1/ai-usage") for _, path in checked)


async def test_the_exempt_routes_work_for_a_flagged_user(client: AsyncClient) -> None:
    await _create_flagged_recruiter()
    await login(client, FLAGGED_EMAIL)

    me = await client.get("/api/v1/auth/me")
    logout = await client.post("/api/v1/auth/logout")

    assert me.status_code == 200
    assert me.json()["must_change_password"] is True
    assert logout.status_code == 204


async def test_changing_the_password_unlocks_the_api(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await _create_flagged_recruiter()
    await login(client, FLAGGED_EMAIL)
    async with signed_in_client(app, FLAGGED_EMAIL) as other_browser:
        assert (await client.get("/api/v1/admin/candidates")).status_code == 403

        response = await client.post(
            CHANGE, json={"current_password": STAFF_PASSWORD, "new_password": NEW_PASSWORD}
        )

        assert response.status_code == 200, response.text
        assert response.json()["must_change_password"] is False
        # The current session stays; every other one of this user ends.
        assert (await client.get("/api/v1/admin/candidates")).status_code == 200
        assert (await other_browser.get("/api/v1/auth/me")).status_code == 401
    user = await db_session.scalar(select(User).where(User.email == FLAGGED_EMAIL))
    assert user is not None
    assert (
        await db_session.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
        )
        == 1
    )
    [event] = list(
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.action == "auth.password_change")
        )
    )
    assert (event.entity_id, event.actor_user_id, event.details) == (user.id, user.id, {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
        assert await _login_raw(fresh, STAFF_PASSWORD) == 401
        assert await _login_raw(fresh, NEW_PASSWORD) == 200


async def test_a_wrong_current_password_is_rejected_and_rate_limited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _create_flagged_recruiter()
    await login(client, FLAGGED_EMAIL)
    wrong = {"current_password": "not-the-password", "new_password": NEW_PASSWORD}

    for _ in range(5):
        response = await client.post(CHANGE, json=wrong)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_current_password"

    blocked = await client.post(CHANGE, json=wrong)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    # Even the right password is refused while the limit holds.
    right = {"current_password": STAFF_PASSWORD, "new_password": NEW_PASSWORD}
    assert (await client.post(CHANGE, json=right)).status_code == 429
    flagged = await db_session.scalar(
        select(User.must_change_password).where(User.email == FLAGGED_EMAIL)
    )
    assert flagged is True


async def test_the_new_password_must_differ_from_the_current_one(client: AsyncClient) -> None:
    await _create_flagged_recruiter()
    await login(client, FLAGGED_EMAIL)

    response = await client.post(
        CHANGE, json={"current_password": STAFF_PASSWORD, "new_password": STAFF_PASSWORD}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["errors"][0]["loc"] == ["body", "new_password"]


async def test_a_short_new_password_and_unknown_fields_are_422(client: AsyncClient) -> None:
    await _create_flagged_recruiter()
    await login(client, FLAGGED_EMAIL)

    short = await client.post(
        CHANGE, json={"current_password": STAFF_PASSWORD, "new_password": "short"}
    )
    extra = await client.post(
        CHANGE,
        json={"current_password": STAFF_PASSWORD, "new_password": NEW_PASSWORD, "role": "admin"},
    )

    assert (short.status_code, extra.status_code) == (422, 422)


async def test_unflagged_users_can_change_their_password_too(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    response = await admin_client.post(
        CHANGE, json={"current_password": STAFF_PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
        login_response = await fresh.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": NEW_PASSWORD},
            headers=FETCH_HEADERS,
        )
        assert login_response.status_code == 200


async def test_change_password_requires_a_session_and_the_csrf_header(client: AsyncClient) -> None:
    body = {"current_password": STAFF_PASSWORD, "new_password": NEW_PASSWORD}

    no_header = await client.post(CHANGE, json=body)
    anonymous = await client.post(CHANGE, json=body, headers=FETCH_HEADERS)

    assert no_header.status_code == 403
    assert no_header.json()["error"]["code"] == "csrf_failed"
    assert anonymous.status_code == 401
