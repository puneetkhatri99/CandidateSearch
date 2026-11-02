"""All database queries for saved searches. Every read is scoped to the owner's user id."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, ScalarSelect, delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.semantic_search.models import SavedSearch, SavedSearchMatch


async def add_saved_search(
    session: AsyncSession, search: SavedSearch, matches: Sequence[SavedSearchMatch]
) -> None:
    session.add(search)
    await session.flush()  # the id the matches point at
    for match in matches:
        match.saved_search_id = search.id
    session.add_all(matches)
    await session.flush()


async def prune_history(session: AsyncSession, user_id: uuid.UUID, keep: int) -> None:
    """Delete the owner's un-starred searches beyond the newest `keep`; their matches cascade."""
    older = (
        select(SavedSearch.id)
        .where(SavedSearch.user_id == user_id, SavedSearch.starred.is_(False))
        .order_by(SavedSearch.created_at.desc(), SavedSearch.id.desc())
        .offset(keep)
    )
    await session.execute(delete(SavedSearch).where(SavedSearch.id.in_(older.scalar_subquery())))


def _count(section: str) -> ScalarSelect[int]:
    return (
        select(func.count())
        .where(
            SavedSearchMatch.saved_search_id == SavedSearch.id,
            SavedSearchMatch.section == section,
        )
        .scalar_subquery()
    )


async def list_saved_searches(
    session: AsyncSession,
    user_id: uuid.UUID,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> Sequence[Row[SavedSearch, int, int]]:
    """Newest first, with result counts; fetches one extra row so the caller can tell whether
    another page exists."""
    statement = (
        select(SavedSearch, _count("items"), _count("filtered_out"))
        .where(SavedSearch.user_id == user_id)
        .order_by(SavedSearch.created_at.desc(), SavedSearch.id.desc())
        .limit(limit + 1)
    )
    if after is not None:
        statement = statement.where(tuple_(SavedSearch.created_at, SavedSearch.id) < tuple_(*after))
    return (await session.execute(statement)).all()


async def get_saved_search(
    session: AsyncSession, saved_search_id: uuid.UUID, user_id: uuid.UUID
) -> SavedSearch | None:
    return await session.scalar(
        select(SavedSearch).where(SavedSearch.id == saved_search_id, SavedSearch.user_id == user_id)
    )


async def get_matches(session: AsyncSession, saved_search_id: uuid.UUID) -> list[SavedSearchMatch]:
    return list(
        await session.scalars(
            select(SavedSearchMatch)
            .where(SavedSearchMatch.saved_search_id == saved_search_id)
            .order_by(SavedSearchMatch.section, SavedSearchMatch.position)
        )
    )


async def delete_saved_search(session: AsyncSession, search: SavedSearch) -> None:
    await session.delete(search)
