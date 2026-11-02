"""Candidate profiles: intake, staff management, and the search document used for matching."""

from app.features.candidates.admin_router import router as admin_router
from app.features.candidates.exceptions import CandidateAlreadyExistsError
from app.features.candidates.router import router
from app.features.candidates.schemas import CandidateCreate, CandidateCreated, CandidateSummary
from app.features.candidates.service import (
    OpenedResume,
    RankableCandidate,
    attach_resume,
    candidate_ids_passing,
    create_candidate,
    full_text_candidate_ids,
    get_rankable_candidates,
    get_resume_ref,
    open_resume,
    rebuild_search_documents,
    record_resume_pdf,
)

__all__ = [
    "CandidateAlreadyExistsError",
    "CandidateCreate",
    "CandidateCreated",
    "CandidateSummary",
    "OpenedResume",
    "RankableCandidate",
    "admin_router",
    "attach_resume",
    "candidate_ids_passing",
    "create_candidate",
    "full_text_candidate_ids",
    "get_rankable_candidates",
    "get_resume_ref",
    "open_resume",
    "rebuild_search_documents",
    "record_resume_pdf",
    "router",
]
