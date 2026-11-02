import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.storage import ObjectStorage, StorageError, discard, get_storage
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
    resume_ref = await candidates.get_resume_ref(session, candidate_id) or uuid.uuid4()
    # The database transaction is closed while ResumeAI works (5-30 s).
    await get_resumeai_client().extract(resume_ref, file)
    await candidates.attach_resume(session, candidate_id, resume_ref, actor)
    logger.info("resume_attached", candidate_id=str(candidate_id))


async def formatted_resume_pdf(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> bytes:
    """The stored copy when there is one; otherwise ResumeAI renders it and a copy is stored.

    Storage problems never fail the request: the PDF then simply comes from ResumeAI.
    """
    opened = await candidates.open_resume(session, candidate_id, actor)
    if opened is None:
        raise NotFoundError("This candidate has no resume yet.")
    store = get_storage()
    if store is not None and opened.pdf_key is not None:
        try:
            stored = await store.get(opened.pdf_key)
        except StorageError as exc:
            logger.warning("resume_pdf_read_failed", candidate_id=str(candidate_id), error=str(exc))
            stored = None
        if stored is not None:
            logger.info("resume_pdf_served", candidate_id=str(candidate_id), source="storage")
            return stored
    pdf = await get_resumeai_client().formatted_pdf(opened.resume_ref)
    logger.info("resume_pdf_served", candidate_id=str(candidate_id), source="resumeai")
    if store is not None:
        await _keep_pdf(session, store, candidate_id, opened, pdf)
    return pdf


async def _keep_pdf(
    session: AsyncSession,
    store: ObjectStorage,
    candidate_id: uuid.UUID,
    opened: candidates.OpenedResume,
    pdf: bytes,
) -> None:
    # A new key per copy: a stale file can never be served under a key that is reused.
    key = f"resumes/{candidate_id}/{uuid.uuid4()}.pdf"
    try:
        await store.put(key, pdf, "application/pdf")
    except StorageError as exc:
        logger.warning("resume_pdf_not_stored", candidate_id=str(candidate_id), error=str(exc))
        return
    if await candidates.record_resume_pdf(session, candidate_id, key, opened):
        await discard(opened.pdf_key)  # a key whose file had gone missing
    else:
        # The resume or profile changed while ResumeAI was rendering: this copy is already stale.
        await discard(key)
