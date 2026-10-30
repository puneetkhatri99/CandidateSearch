"""The pruning tasks the maintenance runner calls."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.auth import prune_expired_sessions
from app.features.auth.models import UserSession
from tests.integration.conftest import create_staff, login

ME = "/api/v1/auth/me"


async def test_pruning_deletes_only_expired_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_staff("live@example.com")
    await create_staff("gone@example.com")
    await login(client, "gone@example.com")
    async with db_session.begin():
        await db_session.execute(
            text("UPDATE user_sessions SET expires_at = :past"),
            {"past": datetime.now(UTC) - timedelta(minutes=1)},
        )
    client.cookies.clear()
    await login(client, "live@example.com")

    assert await prune_expired_sessions(db_session, batch_size=1) == 1

    async with db_session.begin():
        remaining = list((await db_session.scalars(select(UserSession))).all())
    assert len(remaining) == 1
    # The live session still works.
    assert (await client.get(ME)).status_code == 200
