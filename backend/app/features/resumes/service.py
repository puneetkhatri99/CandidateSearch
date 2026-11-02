import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.features import candidates
from app.features.auth import AuthContext
from app.features.resumes.client import get_resumeai_client
from app.features.resumes.exceptions import UnreadableResumeError
from app.features.resumes.mapping import to_profile
from app.features.resumes.schemas import ResumeRead

logger = structlog.get_logger(__name__)


def _require_file(file: bytes) -> None:
    if not file:
        raise UnreadableResumeError("Choose a resume file to upload.")


async def read_new_resume(file: bytes) -> ResumeRead:
    """For a profile not saved yet: read the resume under a fresh ref and suggest form values.

    Nothing is stored here; the ref is linked when the profile is saved with it. A ref never
    saved leaves its data at ResumeAI unused.
    """
    _require_file(file)
    resume_ref = uuid.uuid4()
    data = await get_resumeai_client().extract(resume_ref, file)
    logger.info("resume_read", resume_ref=str(resume_ref))
    return ResumeRead(resume_ref=resume_ref, profile=to_profile(data))


async def attach_resume(
    session: AsyncSession, candidate_id: uuid.UUID, file: bytes, actor: AuthContext
) -> None:
    """Read a resume for a saved candidate and link it; their profile fields don't change.
    A replacement reuses the candidate's ref, so ResumeAI overwrites the old data."""
    _require_file(file)
    resume_ref = (
        await candidates.get_resume_ref(session, candidate_id, actor, viewing=False) or uuid.uuid4()
    )
    # The database transaction is closed while ResumeAI works (5-30 s).
    await get_resumeai_client().extract(resume_ref, file)
    await candidates.attach_resume(session, candidate_id, resume_ref, actor)
    logger.info("resume_attached", candidate_id=str(candidate_id))


async def formatted_resume_pdf(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> bytes:
    resume_ref = await candidates.get_resume_ref(session, candidate_id, actor, viewing=True)
    if resume_ref is None:
        raise NotFoundError("This candidate has no resume yet.")
    return await get_resumeai_client().formatted_pdf(resume_ref)
