"""Staff account management: /api/v1/admin/users."""

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.features.audit.models import AuditEvent
from app.features.auth import AuthContext, service
from app.features.auth.exceptions import LastAdminError
from app.features.auth.models import User, UserSession
from app.features.auth.schemas import UpdateUserRequest
from tests.integration.conftest import (
    FETCH_HEADERS,
    STAFF_PASSWORD,
    create_staff,
    login,
    signed_in_client,
)

URL = "/api/v1/admin/users"
TEMP_PASSWORD = "temporary-pass-123"


def _new_user(email: str = "new.recruiter@example.com", **overrides: Any) -> dict[str, Any]:
    return {
        "email": email,
        "full_name": "New Recruiter",
        "temporary_password": TEMP_PASSWORD,
        **overrides,
    }


async def _audit(db_session: AsyncSession, action: str) -> list[AuditEvent]:
    result = await db_session.scalars(select(AuditEvent).where(AuditEvent.action == action))
    return list(result)


async def _user(db_session: AsyncSession, email: str) -> User:
    user = await db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    await db_session.refresh(user)
    return user


async def _session_count(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await db_session.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == user_id)
        )
        or 0
    )


# --- Permissions ---------------------------------------------------------------------------


async def test_recruiters_get_403_on_every_user_route(recruiter_client: AsyncClient) -> None:
    other = str(uuid.uuid4())
    calls = [
        ("GET", URL, None),
        ("POST", URL, _new_user()),
        ("PATCH", f"{URL}/{other}", {"is_active": False}),
        ("POST", f"{URL}/{other}/reset-password", {"temporary_password": TEMP_PASSWORD}),
    ]
    for method, url, body in calls:
        response = await recruiter_client.request(method, url, json=body)
        assert response.status_code == 403, (method, url)
        assert response.json()["error"]["code"] == "forbidden"


async def test_anonymous_requests_get_401(client: AsyncClient) -> None:
    response = await client.get(URL)
    assert response.status_code == 401
    response = await client.post(URL, json=_new_user(), headers=FETCH_HEADERS)
    assert response.status_code == 401


# --- Create --------------------------------------------------------------------------------


async def test_admin_creates_a_recruiter_who_must_change_the_password(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.post(URL, json=_new_user())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "recruiter"
    assert body["is_active"] is True
    assert body["must_change_password"] is True
    assert body["last_login_at"] is None
    assert "password_hash" not in body and TEMP_PASSWORD not in str(body)
    user = await _user(db_session, "new.recruiter@example.com")
    assert user.password_hash.startswith("$argon2id$")
    [event] = await _audit(db_session, "user.create")
    assert event.entity_id == user.id
    assert event.details == {"role": "recruiter"}
    assert "new.recruiter" not in str(event.details) and "New Recruiter" not in str(event.details)


async def test_admin_can_create_another_admin(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.post(URL, json=_new_user("second@example.com", role="admin"))

    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    [event] = await _audit(db_session, "user.create")
    assert event.details == {"role": "admin"}


async def test_duplicate_email_is_a_conflict_and_leaves_no_audit_row(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    assert (await admin_client.post(URL, json=_new_user())).status_code == 201

    again = await admin_client.post(URL, json=_new_user("NEW.recruiter@example.com"))

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "user_exists"
    assert len(await _audit(db_session, "user.create")) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"temporary_password": "short"},
        {"temporary_password": "x" * 201},
        {"email": "not-an-email"},
        {"full_name": "A"},
        {"role": "owner"},
        {"unknown": 1},
        {"full_name": "Bad\x00Name"},
    ],
)
async def test_invalid_create_bodies_are_422(
    admin_client: AsyncClient, overrides: dict[str, Any]
) -> None:
    response = await admin_client.post(URL, json=_new_user(**overrides))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_a_temporary_password_with_surrounding_spaces_is_kept_as_typed(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    password = "  spaced password  "
    assert (
        await admin_client.post(URL, json=_new_user(temporary_password=password))
    ).status_code == 201

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        response = await other.post(
            "/api/v1/auth/login",
            json={"email": "new.recruiter@example.com", "password": password},
            headers=FETCH_HEADERS,
        )
    assert response.status_code == 200


# --- Deactivate / reactivate ---------------------------------------------------------------


async def test_deactivating_deletes_sessions_and_blocks_login_until_reactivated(
    admin_client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    created = (await admin_client.post(URL, json=_new_user("staff@example.com"))).json()
    user_id = uuid.UUID(created["id"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as phone:  # noqa: SIM117 - the body would need re-indenting for no gain
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as laptop:
            for client in (phone, laptop):
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "staff@example.com", "password": TEMP_PASSWORD},
                    headers=FETCH_HEADERS,
                )
                assert response.status_code == 200
            assert await _session_count(db_session, user_id) == 2

            response = await admin_client.patch(f"{URL}/{user_id}", json={"is_active": False})

            assert response.status_code == 200
            assert response.json()["is_active"] is False
            assert await _session_count(db_session, user_id) == 0
            for client in (phone, laptop):
                assert (await client.get("/api/v1/auth/me")).status_code == 401
            denied = await phone.post(
                "/api/v1/auth/login",
                json={"email": "staff@example.com", "password": TEMP_PASSWORD},
                headers=FETCH_HEADERS,
            )
            assert denied.status_code == 401
            assert denied.json()["error"]["code"] == "invalid_credentials"

            reactivated = await admin_client.patch(f"{URL}/{user_id}", json={"is_active": True})
            assert reactivated.json()["is_active"] is True
            # Old cookies stay dead: the sessions were deleted, not suspended.
            assert (await laptop.get("/api/v1/auth/me")).status_code == 401
            again = await phone.post(
                "/api/v1/auth/login",
                json={"email": "staff@example.com", "password": TEMP_PASSWORD},
                headers=FETCH_HEADERS,
            )
            assert again.status_code == 200

    updates = await _audit(db_session, "user.update")
    assert [event.details["changed_fields"] for event in updates] == [["is_active"], ["is_active"]]
    assert [event.details["is_active"] for event in updates] == [False, True]


async def test_an_update_with_nothing_to_change_is_rejected(admin_client: AsyncClient) -> None:
    created = (await admin_client.post(URL, json=_new_user())).json()

    response = await admin_client.patch(f"{URL}/{created['id']}", json={})

    assert response.status_code == 422


async def test_unknown_user_is_404(admin_client: AsyncClient) -> None:
    missing = uuid.uuid4()
    patch = await admin_client.patch(f"{URL}/{missing}", json={"is_active": False})
    reset = await admin_client.post(
        f"{URL}/{missing}/reset-password", json={"temporary_password": TEMP_PASSWORD}
    )

    assert (patch.status_code, reset.status_code) == (404, 404)
    assert patch.json()["error"]["code"] == "not_found"


# --- Role changes --------------------------------------------------------------------------


async def test_a_demoted_admin_loses_access_on_the_next_request(
    admin_client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    second = await create_staff("second-admin@example.com", "admin")
    async with signed_in_client(app, "second-admin@example.com") as second_client:
        assert (await second_client.get(URL)).status_code == 200

        response = await admin_client.patch(f"{URL}/{second.id}", json={"role": "recruiter"})

        assert response.status_code == 200
        assert (await second_client.get(URL)).status_code == 403
        assert (await second_client.get("/api/v1/auth/me")).json()["role"] == "recruiter"
    [event] = await _audit(db_session, "user.update")
    assert event.details == {"changed_fields": ["role"], "role": "recruiter", "is_active": True}


# --- Self protection -----------------------------------------------------------------------


async def test_an_admin_cannot_deactivate_demote_or_reset_themselves(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    me = (await admin_client.get("/api/v1/auth/me")).json()["id"]

    for response in (
        await admin_client.patch(f"{URL}/{me}", json={"is_active": False}),
        await admin_client.patch(f"{URL}/{me}", json={"role": "recruiter"}),
        await admin_client.post(
            f"{URL}/{me}/reset-password", json={"temporary_password": TEMP_PASSWORD}
        ),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cannot_modify_self"
    assert (await admin_client.get(URL)).status_code == 200
    assert await _audit(db_session, "user.update") == []
    assert await _audit(db_session, "user.password_reset") == []


# --- Reset ---------------------------------------------------------------------------------


async def test_reset_flags_the_account_ends_its_sessions_and_sets_the_new_password(
    admin_client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    staff = await create_staff("staff@example.com", "recruiter")
    async with signed_in_client(app, "staff@example.com") as staff_client:
        assert (await staff_client.get("/api/v1/admin/candidates")).status_code == 200

        response = await admin_client.post(
            f"{URL}/{staff.id}/reset-password", json={"temporary_password": "brand-new-temp-1"}
        )

        assert response.status_code == 200
        assert response.json()["must_change_password"] is True
        assert await _session_count(db_session, staff.id) == 0
        assert (await staff_client.get("/api/v1/auth/me")).status_code == 401
        old = await staff_client.post(
            "/api/v1/auth/login",
            json={"email": "staff@example.com", "password": STAFF_PASSWORD},
            headers=FETCH_HEADERS,
        )
        assert old.status_code == 401
        fresh = await staff_client.post(
            "/api/v1/auth/login",
            json={"email": "staff@example.com", "password": "brand-new-temp-1"},
            headers=FETCH_HEADERS,
        )
        assert fresh.status_code == 200
        assert fresh.json()["must_change_password"] is True
        assert (await staff_client.get("/api/v1/admin/candidates")).status_code == 403
    [event] = await _audit(db_session, "user.password_reset")
    assert event.entity_id == staff.id
    assert event.details == {}


# --- Pagination ----------------------------------------------------------------------------


async def test_pages_have_no_gaps_or_duplicates(admin_client: AsyncClient) -> None:
    for index in range(6):
        assert (
            await admin_client.post(URL, json=_new_user(f"u{index}@example.com"))
        ).status_code == 201

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await admin_client.get(URL, params=params)).json()
        seen.extend(item["email"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 7  # six recruiters and the admin
    assert seen[0] == "u5@example.com"  # newest first


async def test_page_size_is_capped_and_bad_cursors_are_400(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(URL, params={"limit": 101})).status_code == 422
    assert (await admin_client.get(URL, params={"limit": 0})).status_code == 422

    bad = await admin_client.get(URL, params={"cursor": "not-a-cursor"})

    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "invalid_cursor"


async def test_login_still_works_for_a_cli_created_admin(client: AsyncClient) -> None:
    await create_staff("cli-admin@example.com", "admin")
    await login(client, "cli-admin@example.com")

    me = (await client.get("/api/v1/auth/me")).json()

    assert me["must_change_password"] is False


# --- Last admin ----------------------------------------------------------------------------


@pytest.mark.parametrize("body", [{"role": "recruiter"}, {"is_active": False}])
async def test_two_admins_cannot_remove_each_other_at_the_same_time(
    db_session: AsyncSession, body: dict[str, Any]
) -> None:
    """Both requests were authorised while both were admins, then race inside the service."""
    first = await create_staff("first-admin@example.com", "admin")
    second = await create_staff("second-admin@example.com", "admin")

    def context(user: Any) -> AuthContext:
        return AuthContext(
            user_id=user.id, email=user.email, full_name=user.full_name, role="admin", ip=None
        )

    async def remove(actor: Any, target: Any) -> None:
        async with get_sessionmaker()() as session:
            await service.update_user(
                session, context(actor), target.id, UpdateUserRequest.model_validate(body)
            )

    outcomes = await asyncio.gather(
        remove(first, second), remove(second, first), return_exceptions=True
    )

    failures = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(failures) == 1, outcomes
    assert isinstance(failures[0], LastAdminError)
    assert failures[0].code == "last_admin"
    assert failures[0].status_code == 409
    admins = await db_session.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
    )
    assert admins == 1


async def test_removing_an_admin_is_allowed_while_another_stays(
    admin_client: AsyncClient,
) -> None:
    other = await create_staff("other-admin@example.com", "admin")

    response = await admin_client.patch(f"{URL}/{other.id}", json={"role": "recruiter"})

    assert response.status_code == 200


# --- No-op updates and rate limit ----------------------------------------------------------


async def test_an_update_that_changes_nothing_is_ok_and_writes_no_audit_row(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    created = (await admin_client.post(URL, json=_new_user())).json()

    response = await admin_client.patch(f"{URL}/{created['id']}", json={"is_active": True})

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert await _audit(db_session, "user.update") == []


async def test_creating_and_resetting_are_rate_limited_per_admin(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "admin_account_write_limit", 2)
    first = (await admin_client.post(URL, json=_new_user("a@example.com"))).json()
    assert (
        await admin_client.post(
            f"{URL}/{first['id']}/reset-password", json={"temporary_password": TEMP_PASSWORD}
        )
    ).status_code == 200

    blocked = await admin_client.post(URL, json=_new_user("b@example.com"))

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) > 0
    # Reads and updates are not part of the limit.
    assert (await admin_client.get(URL)).status_code == 200
    assert (
        await admin_client.patch(f"{URL}/{first['id']}", json={"is_active": False})
    ).status_code == 200
