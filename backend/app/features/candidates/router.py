from fastapi import APIRouter, Depends, status

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.rate_limit import rate_limit
from app.features.candidates import service
from app.features.candidates.schemas import CandidateCreate, CandidateCreated

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            rate_limit(
                "candidate_submit",
                limit=lambda: get_settings().candidate_submit_limit,
                window_seconds=lambda: get_settings().candidate_submit_window_seconds,
            )
        ),
    ],
)
async def submit_candidate(payload: CandidateCreate, session: SessionDep) -> CandidateCreated:
    """Public candidate intake form submission. Body size is capped by BodySizeLimitMiddleware."""
    return await service.create_candidate(
        session, payload, consent_version=get_settings().privacy_notice_version
    )
