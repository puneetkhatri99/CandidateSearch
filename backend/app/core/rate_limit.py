"""Postgres-backed sliding-window rate limiting, exact and shared by every API process.

Each hit is a row in `rate_limit_hits`. Checking the window and recording a hit happen in one
transaction under a per-key advisory lock, so concurrent callers queue on the lock and each
sees the previous caller's row: at most `limit` hits can exist in any window.

Keys are "<scope>:" plus an HMAC of the identity (email, IP, user id), so no raw personal data
is stored. A plain hash of an email could be reversed by hashing a list of staff emails.
"""

import hashlib
import hmac
import math
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import structlog
from fastapi import Request
from sqlalchemy import DateTime, Index, String, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.db import SessionDep, TimestampedModel
from app.core.errors import RateLimitedError

logger = structlog.get_logger(__name__)

# The two-int advisory lock form has its own lock space, so these never collide with the
# single-bigint budget and admin locks.
RATE_LIMIT_LOCK_NAMESPACE = 7_240_040
PRUNE_BATCH_SIZE = 1000


class RateLimitHit(TimestampedModel):
    """One counted request. Lives in core because auth and candidates both use the limiter."""

    __tablename__ = "rate_limit_hits"
    __table_args__ = (Index("ix_rate_limit_hits_key_created_at", "key", "created_at"),)

    # "<scope>:<hmac-sha256 hex>"; never an email, IP or id in clear text.
    key: Mapped[str] = mapped_column(String(100))
    # When the hit leaves its window; the prune deletes by this.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


def rate_limit_key(scope: str, *identity: str) -> str:
    secret = get_settings().rate_limit_key_secret.get_secret_value().encode()
    # NUL-separated so ("a:b", "c") and ("a", "b:c") can't produce the same key.
    digest = hmac.new(secret, "\x00".join(identity).encode(), hashlib.sha256).hexdigest()
    return f"{scope}:{digest}"


async def acquire_slot(
    session: AsyncSession, key: str, *, limit: int, window_seconds: int, message: str
) -> uuid.UUID:
    """Count the hits in the window and record one more, or raise RateLimitedError.

    `session` must not be in a transaction; the lock is held only for this short one.
    """
    window = timedelta(seconds=window_seconds)
    hit_id = uuid.uuid4()
    async with session.begin():
        await session.execute(
            select(func.pg_advisory_xact_lock(RATE_LIMIT_LOCK_NAMESPACE, func.hashtext(key)))
        )
        # clock_timestamp, not now(): now() is the transaction start, stale after a lock wait.
        now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
        hits = list(
            (
                await session.scalars(
                    select(RateLimitHit.created_at)
                    .where(RateLimitHit.key == key, RateLimitHit.created_at > now - window)
                    .order_by(RateLimitHit.created_at)
                )
            ).all()
        )
        if len(hits) >= limit:
            # The hit whose expiry brings the count back under the limit.
            frees_at = hits[len(hits) - limit] + window
            retry_after = max(math.ceil((frees_at - now).total_seconds()), 1)
            raise RateLimitedError(message, headers={"Retry-After": str(retry_after)})
        session.add(RateLimitHit(id=hit_id, key=key, created_at=now, expires_at=now + window))
    return hit_id


async def release_slot(session: AsyncSession, hit_id: uuid.UUID) -> None:
    """Delete a hit: the attempt it guarded did not count (e.g. a correct password)."""
    async with session.begin():
        await session.execute(delete(RateLimitHit).where(RateLimitHit.id == hit_id))


async def _release_quietly(session: AsyncSession, hit_id: uuid.UUID) -> None:
    try:
        if session.in_transaction():
            await session.rollback()
        await release_slot(session, hit_id)
    except Exception as exc:
        # Keeping the hit errs toward counting (fail closed); the attempt's own outcome stands.
        logger.warning("rate_limit_release_failed", error_type=type(exc).__name__)


@asynccontextmanager
async def failure_slot(
    session: AsyncSession,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    message: str,
    counts_as_failure: tuple[type[BaseException], ...],
) -> AsyncIterator[None]:
    """Reserve a slot before an attempt and keep it only if the attempt fails as counted.

    Reserving first is what makes failure-only counting race-free: while N attempts are in
    flight they each hold a slot, so they can't all pass the check before any is recorded.
    A cancelled attempt keeps its slot, which only hurts the caller who cancelled.
    """
    hit_id = await acquire_slot(
        session, key, limit=limit, window_seconds=window_seconds, message=message
    )
    try:
        yield
    except counts_as_failure:
        raise
    except Exception:
        await _release_quietly(session, hit_id)
        raise
    await _release_quietly(session, hit_id)


async def prune_rate_limit_hits(session: AsyncSession) -> int:
    """Delete hits whose window has ended, in batches; returns how many."""
    total = 0
    while True:
        async with session.begin():
            expired = (
                select(RateLimitHit.id)
                .where(RateLimitHit.expires_at < func.now())
                .limit(PRUNE_BATCH_SIZE)
            )
            result = await session.execute(
                delete(RateLimitHit).where(RateLimitHit.id.in_(expired.scalar_subquery()))
            )
        deleted = int(result.rowcount)  # type: ignore[attr-defined]
        total += deleted
        if deleted < PRUNE_BATCH_SIZE:
            return total


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, run uvicorn with --proxy-headers so this is the real client IP.
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str, limit: Callable[[], int], window_seconds: Callable[[], int]
) -> Callable[[Request, AsyncSession], Awaitable[None]]:
    """FastAPI dependency limiting requests per client IP within `scope`; every request counts.

    Limits are callables so they're read from settings at request time.
    """

    async def dependency(request: Request, session: SessionDep) -> None:
        await acquire_slot(
            session,
            rate_limit_key(scope, client_ip(request)),
            limit=limit(),
            window_seconds=window_seconds(),
            message="Too many requests. Please try again later.",
        )

    return dependency
