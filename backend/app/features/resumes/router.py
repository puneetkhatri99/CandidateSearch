"""Resume upload and the formatted resume. The file is sent as the raw request body (not
multipart), so no form-parsing dependency is needed; BodySizeLimitMiddleware caps it."""

import uuid

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.rate_limit import rate_limit
from app.features.auth import CurrentUser, require_fetch_header_on_any_method
from app.features.resumes import service
from app.features.resumes.schemas import ResumeRead

router = APIRouter(tags=["resumes"])


@router.post(
    "/resumes",
    dependencies=[
        # Public, and each read uses up ResumeAI quota: no cross-site posts, and a per-IP cap.
        Depends(require_fetch_header_on_any_method),
        Depends(
            rate_limit(
                "resume_upload",
                limit=lambda: get_settings().resume_upload_limit,
                window_seconds=lambda: get_settings().resume_upload_window_seconds,
            )
        ),
    ],
)
async def read_resume(request: Request) -> ResumeRead:
    """Read a resume for the profile form (public form and Add candidate)."""
    return await service.read_new_resume(await request.body())


@router.put("/admin/candidates/{candidate_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def attach_resume(
    candidate_id: uuid.UUID, request: Request, session: SessionDep, actor: CurrentUser
) -> None:
    await service.attach_resume(session, candidate_id, await request.body(), actor)


@router.get("/admin/candidates/{candidate_id}/resume")
async def formatted_resume(
    candidate_id: uuid.UUID, session: SessionDep, actor: CurrentUser
) -> Response:
    """The formatted resume PDF, opened in a browser tab. Rendered by ResumeAI on each call."""
    pdf = await service.formatted_resume_pdf(session, candidate_id, actor)
    return Response(
        pdf,
        media_type="application/pdf",
        # A fixed name: the candidate's name would put PII in headers and proxy logs.
        headers={
            "Content-Disposition": 'inline; filename="resume.pdf"',
            "Cache-Control": "no-store",
        },
    )
