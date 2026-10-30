"""Phase 2c item 2: the Postgres-backed rate limiter is exact, race-free and shared."""

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import RateLimitedError
from app.core.rate_limit import (
    RateLimitHit,
    acquire_slot,
    failure_slot,
    prune_rate_limit_hits,
    rate_limit_key,
)
from app.main import create_app
from tests.integration.conftest import FETCH_HEADERS, STAFF_PASSWORD, create_staff

KEY = "test_scope:abc"
LOGIN = "/api/v1/auth/login"


class _CountedError(Exception):
    pass


async def _acquire(key: str = KEY, limit: int = 5, window: int = 60) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        return await acquire_slot(session, key, limit=limit, window_seconds=window, message="slow")


async def _count(key: str | None = None) -> int:
    statement = select(func.count()).select_from(RateLimitHit)
    if key is not None:
        statement = statement.where(RateLimitHit.key == key)
    async with get_sessionmaker()() as session:
        return int(await session.scalar(statement) or 0)


async def _backdate_all(seconds: int) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            text(
                "UPDATE rate_limit_hits SET created_at = created_at - make_interval(secs => :s),"
                " expires_at = expires_at - make_interval(secs => :s)"
            ),
            {"s": seconds},
        )


async def test_allows_up_to_the_limit_then_blocks_with_retry_after() -> None:
    for _ in range(5):
        await _acquire()
    with pytest.raises(RateLimitedError) as blocked:
        await _acquire()
    assert 1 <= int(blocked.value.headers["Retry-After"]) <= 60
    assert await _count(KEY) == 5


async def test_keys_are_counted_separately() -> None:
    await _acquire(limit=1)
    await _acquire(key="test_scope:other", limit=1)
    with pytest.raises(RateLimitedError):
        await _acquire(limit=1)


async def test_the_window_slides_and_retry_after_tracks_the_oldest_blocking_hit() -> None:
    await _acquire(limit=2, window=60)
    await _backdate_all(50)  # first hit is 50 s old
    await _acquire(limit=2, window=60)
    with pytest.raises(RateLimitedError) as blocked:
        await _acquire(limit=2, window=60)
    assert int(blocked.value.headers["Retry-After"]) in (10, 11)

    await _backdate_all(15)  # first hit is now 65 s old: out of the window
    await _acquire(limit=2, window=60)


async def test_twenty_concurrent_callers_get_exactly_the_limit() -> None:
    results = await asyncio.gather(*(_acquire(limit=5) for _ in range(20)), return_exceptions=True)
    assert sum(isinstance(r, uuid.UUID) for r in results) == 5
    assert sum(isinstance(r, RateLimitedError) for r in results) == 15
    assert await _count(KEY) == 5


async def _with_slot(body_error: BaseException | None) -> None:
    async with (
        get_sessionmaker()() as session,
        failure_slot(
            session,
            KEY,
            limit=5,
            window_seconds=60,
            message="x",
            counts_as_failure=(_CountedError,),
        ),
    ):
        if body_error is not None:
            raise body_error


async def test_a_successful_attempt_releases_its_slot() -> None:
    await _with_slot(None)
    assert await _count(KEY) == 0


async def test_a_counted_failure_keeps_its_slot() -> None:
    with pytest.raises(_CountedError):
        await _with_slot(_CountedError())
    assert await _count(KEY) == 1


async def test_any_other_error_releases_the_slot_and_is_re_raised() -> None:
    with pytest.raises(ValueError, match="boom"):
        await _with_slot(ValueError("boom"))
    assert await _count(KEY) == 0


async def test_a_failed_release_is_logged_and_the_original_error_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        def warning(self, event: str, **fields: Any) -> None:
            calls.append((event, fields))

    async def broken_release(_: AsyncSession, __: uuid.UUID) -> None:
        raise ConnectionError("database down")

    monkeypatch.setattr(rate_limit, "logger", Recorder())
    monkeypatch.setattr(rate_limit, "release_slot", broken_release)

    with pytest.raises(ValueError, match="boom"):
        await _with_slot(ValueError("boom"))
    assert calls == [("rate_limit_release_failed", {"error_type": "ConnectionError"})]


async def test_prune_deletes_only_expired_hits() -> None:
    await _acquire(limit=10)
    await _acquire(limit=10)
    await _backdate_all(120)  # both expired (60 s window)
    await _acquire(limit=10)

    async with get_sessionmaker()() as session:
        assert await prune_rate_limit_hits(session) == 2
    assert await _count() == 1


# --- API level --------------------------------------------------------------------------


async def _login(client: AsyncClient, email: str, password: str) -> int:
    response = await client.post(
        LOGIN, json={"email": email, "password": password}, headers=FETCH_HEADERS
    )
    return response.status_code


async def test_concurrent_wrong_passwords_never_exceed_the_limit(client: AsyncClient) -> None:
    await create_staff("target@example.com")
    limit = get_settings().login_failure_limit

    statuses = await asyncio.gather(
        *(_login(client, "target@example.com", "wrong-password-123") for _ in range(10))
    )

    assert statuses.count(401) <= limit
    assert statuses.count(401) + statuses.count(429) == 10
    # The account is now locked for this email + IP, even with the right password.
    assert await _login(client, "target@example.com", STAFF_PASSWORD) == 429


async def test_a_correct_login_is_not_counted(client: AsyncClient) -> None:
    await create_staff("user@example.com")
    for _ in range(4):
        assert await _login(client, "user@example.com", "wrong-password-123") == 401

    assert await _login(client, "user@example.com", STAFF_PASSWORD) == 200
    # Four failures, each counted under the email+IP key and the account key.
    assert await _count() == 8


async def test_the_limit_is_shared_by_two_app_instances() -> None:
    await create_staff("shared@example.com")
    limit = get_settings().login_failure_limit
    first: FastAPI = create_app()
    second: FastAPI = create_app()
    async with (
        AsyncClient(transport=ASGITransport(app=first), base_url="http://test") as a,
        AsyncClient(transport=ASGITransport(app=second), base_url="http://test") as b,
    ):
        for i in range(limit):
            client = a if i % 2 else b
            assert await _login(client, "shared@example.com", "wrong-password-123") == 401
        assert await _login(a, "shared@example.com", "wrong-password-123") == 429
        assert await _login(b, "shared@example.com", "wrong-password-123") == 429


async def test_stored_keys_never_contain_the_email_or_ip(client: AsyncClient) -> None:
    await create_staff("private.person@example.com")
    assert await _login(client, "private.person@example.com", "wrong-password-123") == 401

    async with get_sessionmaker()() as session:
        keys = list((await session.scalars(select(RateLimitHit.key))).all())
    assert sorted(keys) == sorted(
        [
            rate_limit_key("login_failure", "private.person@example.com", "127.0.0.1"),
            rate_limit_key("login_failure_account", "private.person@example.com"),
        ]
    )
    assert all("private" not in key and "127.0.0.1" not in key for key in keys)


async def test_guessing_one_account_from_many_ips_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await create_staff("spread@example.com")
    monkeypatch.setattr(get_settings(), "login_account_failure_limit", 3)
    app = create_app()

    async def login_from(ip: str, password: str) -> int:
        transport = ASGITransport(app=app, client=(ip, 1234))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await _login(client, "spread@example.com", password)

    # Each IP stays far under the per-IP limit of 5.
    for i in range(3):
        assert await login_from(f"10.0.0.{i}", "wrong-password-123") == 401
    assert await login_from("10.0.0.99", "wrong-password-123") == 429
    # The account lock also blocks the right password from a fresh IP until the window ends.
    assert await login_from("10.0.0.100", STAFF_PASSWORD) == 429
