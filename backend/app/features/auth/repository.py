import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.auth.models import User, UserSession


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.lower()))


async def get_user(
    session: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False
) -> User | None:
    statement = select(User).where(User.id == user_id)
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


# Arbitrary constant: every change that can remove an active admin takes this transaction-scoped
# lock first, so two admins cannot demote or deactivate each other at the same time.
ADMIN_CHANGE_LOCK_KEY = 7_240_030_001


async def lock_admin_changes(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_CHANGE_LOCK_KEY}
    )


async def count_active_admins(session: AsyncSession, *, excluding: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", User.is_active.is_(True), User.id != excluding)
    )
    return int(count or 0)


async def add_user(session: AsyncSession, user: User) -> None:
    session.add(user)
    await session.flush()


async def list_users(
    session: AsyncSession, *, after: tuple[datetime, uuid.UUID] | None, limit: int
) -> list[User]:
    """Newest first. Fetches one extra row so the caller can tell whether another page exists."""
    statement = select(User)
    if after is not None:
        statement = statement.where(tuple_(User.created_at, User.id) < tuple_(*after))
    statement = statement.order_by(User.created_at.desc(), User.id.desc()).limit(limit + 1)
    return list((await session.scalars(statement)).all())


async def get_full_names(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    result = await session.execute(select(User.id, User.full_name).where(User.id.in_(set(ids))))
    return {row.id: row.full_name for row in result}


async def add_session(session: AsyncSession, user_session: UserSession) -> None:
    session.add(user_session)
    await session.flush()


async def get_live_session(
    session: AsyncSession, token_hash: str, now: datetime
) -> tuple[UserSession, User] | None:
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.expires_at > now,
                User.is_active.is_(True),
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


async def delete_session(session: AsyncSession, token_hash: str) -> None:
    await session.execute(delete(UserSession).where(UserSession.token_hash == token_hash))


async def delete_expired_sessions(session: AsyncSession, now: datetime, *, limit: int) -> int:
    """Delete up to `limit` expired sessions; returns how many were deleted."""
    expired = select(UserSession.id).where(UserSession.expires_at < now).limit(limit)
    result = await session.execute(
        delete(UserSession).where(UserSession.id.in_(expired.scalar_subquery()))
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


async def delete_sessions_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, except_token_hash: str | None = None
) -> None:
    statement = delete(UserSession).where(UserSession.user_id == user_id)
    if except_token_hash is not None:
        statement = statement.where(UserSession.token_hash != except_token_hash)
    await session.execute(statement)
