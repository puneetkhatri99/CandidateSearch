"""Staff-only search by meaning. A separate prefix keeps it clear of /admin/candidates/{id}."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.core.db import SessionDep
from app.features.auth import CurrentUser, require_fetch_header_on_any_method
from app.features.semantic_search import history, service
from app.features.semantic_search.schemas import (
    SavedSearchDetail,
    SavedSearchPage,
    SemanticSearchParams,
    SemanticSearchResult,
    StarRequest,
)
from app.features.semantic_search.streaming import stream_search

# Most routes here are paid AI calls, so even GETs need the CSRF header (the saved-search
# routes are free, and need it only for being on this router).
router = APIRouter(
    prefix="/semantic-search",
    tags=["semantic search"],
    dependencies=[Depends(require_fetch_header_on_any_method)],
)


@router.get("/candidates")
async def search_candidates_by_meaning(
    params: Annotated[SemanticSearchParams, Query()], session: SessionDep, actor: CurrentUser
) -> SemanticSearchResult:
    return await service.search_by_meaning(session, params, actor)


@router.get("/candidates/stream", response_class=StreamingResponse)
async def stream_search_candidates(
    params: Annotated[SemanticSearchParams, Query()], actor: CurrentUser
) -> StreamingResponse:
    """The same search as server-sent events: `stage` per step, then `result` or `error`."""
    return stream_search(
        lambda session, progress: service.search_by_meaning(session, params, actor, progress)
    )


@router.get("/jobs/{job_id}/candidates/stream", response_class=StreamingResponse)
async def stream_match_candidates_to_job(
    job_id: uuid.UUID, actor: CurrentUser
) -> StreamingResponse:
    """The same job match as server-sent events: `stage` per step, then `result` or `error`."""
    return stream_search(
        lambda session, progress: service.match_job(session, job_id, actor, progress)
    )


@router.get("/jobs/{job_id}/candidates")
async def match_candidates_to_job(
    job_id: uuid.UUID, session: SessionDep, actor: CurrentUser
) -> SemanticSearchResult:
    """A paid AI ranking (about $0.02), so the UI calls it only on request."""
    return await service.match_job(session, job_id, actor)


@router.get("/history")
async def list_saved_searches(
    session: SessionDep,
    actor: CurrentUser,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> SavedSearchPage:
    """Your own past searches, newest first. Free: nothing is re-run."""
    return await history.list_history(session, actor, cursor)


@router.get("/history/{saved_search_id}")
async def get_saved_search(
    saved_search_id: uuid.UUID, session: SessionDep, actor: CurrentUser
) -> SavedSearchDetail:
    """One of your searches with its result as it was ranked. Free: no AI call."""
    return await history.get_saved_search(session, actor, saved_search_id)


@router.put("/history/{saved_search_id}/star", status_code=status.HTTP_204_NO_CONTENT)
async def star_saved_search(
    saved_search_id: uuid.UUID, body: StarRequest, session: SessionDep, actor: CurrentUser
) -> None:
    await history.star_saved_search(session, actor, saved_search_id, body.starred)


@router.delete("/history/{saved_search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search(
    saved_search_id: uuid.UUID, session: SessionDep, actor: CurrentUser
) -> None:
    await history.delete_saved_search(session, actor, saved_search_id)
