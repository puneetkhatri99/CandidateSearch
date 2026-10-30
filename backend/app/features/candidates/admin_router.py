"""Staff-only candidate management. Every route requires a signed-in user."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.config import get_settings
from app.core.db import SessionDep
from app.features.auth import AdminUser, CurrentUser
from app.features.candidates import service
from app.features.candidates.schemas import (
    CandidateDetail,
    CandidatePage,
    CandidateSearchParams,
    CandidateUpdate,
    StaffCandidateCreate,
)

router = APIRouter(prefix="/admin/candidates", tags=["admin: candidates"])


@router.get("")
async def search_candidates(
    params: Annotated[CandidateSearchParams, Query()], session: SessionDep, actor: CurrentUser
) -> CandidatePage:
    return await service.search_candidates(session, params, actor)


@router.get("/{candidate_id}")
async def get_candidate(
    candidate_id: uuid.UUID, session: SessionDep, actor: CurrentUser
) -> CandidateDetail:
    return await service.get_candidate(session, candidate_id, actor)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_candidate(
    payload: StaffCandidateCreate, session: SessionDep, actor: CurrentUser
) -> CandidateDetail:
    return await service.create_candidate_by_staff(
        session, payload, actor, consent_version=get_settings().privacy_notice_version
    )


@router.put("/{candidate_id}")
async def update_candidate(
    candidate_id: uuid.UUID, payload: CandidateUpdate, session: SessionDep, actor: CurrentUser
) -> CandidateDetail:
    return await service.update_candidate(session, candidate_id, payload, actor)


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(candidate_id: uuid.UUID, session: SessionDep, actor: AdminUser) -> None:
    await service.delete_candidate(session, candidate_id, actor)
