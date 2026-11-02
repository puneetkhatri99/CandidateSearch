"""Saved searches (user decisions 2026-11-02): every search by meaning is saved with its result,
each person sees only their own, the newest 50 un-starred are kept, and starred ones stay.

Reopening a saved search shows the result as it was ranked, with each candidate's current
summary; it makes no AI call. The query text is stored for its owner only, and still never
logged or audited.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import decode_created_at_cursor, next_created_at_cursor
from app.features import candidates
from app.features.auth import AuthContext
from app.features.semantic_search import repository
from app.features.semantic_search.exceptions import SavedSearchNotFoundError
from app.features.semantic_search.models import HISTORY_LIMIT, SavedSearch, SavedSearchMatch
from app.features.semantic_search.schemas import (
    Criterion,
    SavedSearchDetail,
    SavedSearchPage,
    SavedSearchSummary,
    SemanticMatch,
    SemanticSearchParams,
    SemanticSearchResult,
)

PAGE_SIZE = 50
# The filters a recruiter sets, as the page puts them in the URL; reopening rebuilds that URL.
_URL_FILTERS = {"min_years", "skill", "city", "country", "source"}


def _url_filters(params: SemanticSearchParams) -> dict[str, Any]:
    values = params.model_dump(mode="json", include=_URL_FILTERS, exclude_none=True)
    return {name: value for name, value in values.items() if value != ""}


def _match_rows(result: SemanticSearchResult) -> list[SavedSearchMatch]:
    rows = []
    for section, matches in (("items", result.items), ("filtered_out", result.filtered_out)):
        for position, match in enumerate(matches):
            rows.append(
                SavedSearchMatch(
                    candidate_id=match.candidate.id,
                    section=section,
                    position=position,
                    fit=match.fit,
                    criteria=[c.model_dump(mode="json") for c in match.criteria],
                    failed_filters=list(match.failed_filters),
                )
            )
    return rows


async def save_search(
    session: AsyncSession,
    user_id: uuid.UUID,
    params: SemanticSearchParams,
    result: SemanticSearchResult,
) -> uuid.UUID:
    """Store a finished search and drop the owner's oldest un-starred ones beyond the limit.
    Runs in the caller's transaction (the one that writes the search's audit row)."""
    search = SavedSearch(
        user_id=user_id,
        query=params.q,
        filters=_url_filters(params),
        checked=result.checked,
        ranked_by=result.ranked_by,
        embedding_model=result.embedding_model,
        ranking_model=result.ranking_model,
        prompt_version=result.prompt_version,
    )
    await repository.add_saved_search(session, search, _match_rows(result))
    await repository.prune_history(session, user_id, HISTORY_LIMIT)
    return search.id


async def list_history(
    session: AsyncSession, actor: AuthContext, cursor: str | None
) -> SavedSearchPage:
    after = decode_created_at_cursor(cursor)
    async with session.begin():
        rows = await repository.list_saved_searches(session, actor.user_id, after, PAGE_SIZE)
    searches: list[SavedSearch] = []
    counts: dict[uuid.UUID, tuple[int, int]] = {}
    for search, item_count, filtered_out_count in rows:
        searches.append(search)
        counts[search.id] = (item_count, filtered_out_count)
    page, next_cursor = next_created_at_cursor(searches, PAGE_SIZE)
    return SavedSearchPage(
        items=[
            SavedSearchSummary(
                id=search.id,
                query=search.query,
                filters=search.filters,
                result_count=counts[search.id][0],
                filtered_out_count=counts[search.id][1],
                starred=search.starred,
                created_at=search.created_at,
            )
            for search in page
        ],
        next_cursor=next_cursor,
    )


async def get_saved_search(
    session: AsyncSession, actor: AuthContext, saved_search_id: uuid.UUID
) -> SavedSearchDetail:
    """The saved result with current summaries; candidates deleted since are simply absent
    (their match rows were deleted with them)."""
    async with session.begin():
        search = await repository.get_saved_search(session, saved_search_id, actor.user_id)
        if search is None:
            raise SavedSearchNotFoundError("This saved search is no longer available.")
        matches = await repository.get_matches(session, search.id)
    found = await candidates.get_rankable_candidates(session, [m.candidate_id for m in matches])

    def section(name: str) -> list[SemanticMatch]:
        return [
            SemanticMatch(
                candidate=found[m.candidate_id].summary,
                fit=m.fit,
                criteria=[Criterion.model_validate(c) for c in m.criteria],
                failed_filters=m.failed_filters,
            )
            for m in matches
            if m.section == name and m.candidate_id in found
        ]

    result = SemanticSearchResult(
        items=section("items"),
        filtered_out=section("filtered_out"),
        checked=search.checked,
        ranked_by=search.ranked_by,
        embedding_model=search.embedding_model,
        ranking_model=search.ranking_model,
        prompt_version=search.prompt_version,
        saved_search_id=search.id,
    )
    return SavedSearchDetail(
        query=search.query,
        filters=search.filters,
        starred=search.starred,
        created_at=search.created_at,
        result=result,
    )


async def star_saved_search(
    session: AsyncSession, actor: AuthContext, saved_search_id: uuid.UUID, starred: bool
) -> None:
    async with session.begin():
        search = await repository.get_saved_search(session, saved_search_id, actor.user_id)
        if search is None:
            raise SavedSearchNotFoundError("This saved search is no longer available.")
        search.starred = starred


async def delete_saved_search(
    session: AsyncSession, actor: AuthContext, saved_search_id: uuid.UUID
) -> None:
    async with session.begin():
        search = await repository.get_saved_search(session, saved_search_id, actor.user_id)
        if search is None:
            raise SavedSearchNotFoundError("This saved search is no longer available.")
        await repository.delete_saved_search(session, search)
