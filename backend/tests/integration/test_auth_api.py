import hashlib
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.audit.models import AuditEvent
from app.features.auth.models import User, UserSession
from tests.integration.conftest import FETCH_HEADERS, STAFF_PASSWORD, create_staff, login

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


async def _login(client: AsyncClient, email: str, password: str) -> int:
    response = await client.post(
        LOGIN, json={"email": email, "password": password}, headers=FETCH_HEADERS
    )
    return response.status_code


async def test_login_sets_httponly_session_cookie_and_me_works(client: AsyncClient) -> None:
    await create_staff("Admin@Example.com")

    response = await client.post(
        LOGIN,
        json={"email": "ADMIN@example.com", "password": STAFF_PASSWORD},
        headers=FETCH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert (await client.get(ME)).json()["role"] == "admin"


async def test_wrong_password_and_unknown_email_get_the_same_error(client: AsyncClient) -> None:
    await create_staff("admin@example.com")

    wrong = await client.post(
        LOGIN, json={"email": "admin@example.com", "password": "nope"}, headers=FETCH_HEADERS
    )
    unknown = await client.post(
        LOGIN, json={"email": "who@example.com", "password": "nope"}, headers=FETCH_HEADERS
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "invalid_credentials"


async def test_login_requires_csrf_header(client: AsyncClient) -> None:
    await create_staff("admin@example.com")

    response = await client.post(
        LOGIN, json={"email": "admin@example.com", "password": STAFF_PASSWORD}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_locked_out_after_repeated_failures(client: AsyncClient) -> None:
    await create_staff("admin@example.com")
    for _ in range(get_settings().login_failure_limit):
        assert await _login(client, "admin@example.com", "wrong-password") == 401

    response = await client.post(
        LOGIN,
        json={"email": "admin@example.com", "password": STAFF_PASSWORD},
        headers=FETCH_HEADERS,
    )

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


async def test_successful_logins_do_not_count_towards_lockout(client: AsyncClient) -> None:
    await create_staff("admin@example.com")
    for _ in range(get_settings().login_failure_limit + 2):
        assert await _login(client, "admin@example.com", STAFF_PASSWORD) == 200


async def test_logout_revokes_session_server_side(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_staff("admin@example.com")
    await login(client, "admin@example.com")
    cookie_name = get_settings().session_cookie_name
    token = client.cookies[cookie_name]

    assert (await client.post("/api/v1/auth/logout")).status_code == 204

    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 0
    # Replaying the old cookie must not work.
    client.cookies.set(cookie_name, token)
    assert (await client.get(ME)).status_code == 401


async def test_only_token_hash_is_stored(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_staff("admin@example.com")
    await login(client, "admin@example.com")
    token = client.cookies[get_settings().session_cookie_name]

    stored = await db_session.scalar(select(UserSession.token_hash))

    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert stored != token


async def test_password_stored_as_argon2id(db_session: AsyncSession) -> None:
    await create_staff("admin@example.com")

    password_hash = await db_session.scalar(select(User.password_hash))

    assert password_hash is not None
    assert password_hash.startswith("$argon2id$")


async def test_expired_session_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_staff("admin@example.com")
    await login(client, "admin@example.com")
    async with db_session.begin():
        await db_session.execute(
            update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )

    assert (await client.get(ME)).status_code == 401


async def test_deactivated_user_cannot_log_in_or_use_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_staff("admin@example.com")
    await login(client, "admin@example.com")
    async with db_session.begin():
        await db_session.execute(update(User).values(is_active=False))

    assert (await client.get(ME)).status_code == 401
    assert await _login(client, "admin@example.com", STAFF_PASSWORD) == 401


async def test_no_cookie_is_401(client: AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_login_and_logout_are_audited(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_staff("admin@example.com")
    await login(client, "admin@example.com")
    await client.post("/api/v1/auth/logout")

    actions = (await db_session.scalars(select(AuditEvent.action))).all()

    assert sorted(actions) == ["auth.login", "auth.logout"]
