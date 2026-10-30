"""Candidate profiles: intake, staff management, and the search document used for matching."""

from app.features.candidates.admin_router import router as admin_router
from app.features.candidates.exceptions import CandidateAlreadyExistsError
from app.features.candidates.router import router
from app.features.candidates.schemas import CandidateCreate, CandidateCreated, CandidateSummary
from app.features.candidates.service import (
    RankableCandidate,
    candidate_ids_passing,
    create_candidate,
    full_text_candidate_ids,
    get_rankable_candidates,
)

__all__ = [
    "CandidateAlreadyExistsError",
    "CandidateCreate",
    "CandidateCreated",
    "CandidateSummary",
    "RankableCandidate",
    "admin_router",
    "candidate_ids_passing",
    "create_candidate",
    "full_text_candidate_ids",
    "get_rankable_candidates",
    "router",
]
