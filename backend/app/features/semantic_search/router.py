"""Staff-only search by meaning. A separate prefix keeps it clear of /admin/candidates/{id}."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.db import SessionDep
from app.features.auth import CurrentUser, require_fetch_header_on_any_method
from app.features.semantic_search import service
from app.features.semantic_search.schemas import SemanticSearchParams, SemanticSearchResult
from app.features.semantic_search.streaming import stream_search

# Every route here is a paid AI call, so even GETs need the CSRF header.
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
