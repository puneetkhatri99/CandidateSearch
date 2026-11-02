"""The ResumeAI HTTP client: read a resume into data, and render the formatted PDF.

ResumeAI stores the data under a (candidate_id, resume_id) pair we choose; we use our own
`resume_ref` UUID as candidate_id and a fixed resume_id, so one ref is one stored resume.
No retries: both calls are started by a person who can press the button again, and a read
counts against ResumeAI's 30-an-hour limit even when it fails.
"""

import uuid
from urllib.parse import quote

import httpx2
import structlog
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.features.resumes.exceptions import (
    ResumeFileTooLargeError,
    ResumeServiceBusyError,
    ResumeServiceFailedError,
    ResumeServiceUnavailableError,
    UnreadableResumeError,
    UnsupportedResumeFileError,
)
from app.features.resumes.schemas import ResumeAIData, ResumeAIExtractResponse

logger = structlog.get_logger(__name__)

RESUME_ID = "resume"
TEMPLATE_ID = 1
_RESUMES_PATH = "/api/public/resumes"
_UNREADABLE = "We couldn't read this resume. Check the file, or fill in the form yourself."


class ResumeAIClient:
    def __init__(
        self, *, api_key: str, base_url: str, timeout_seconds: float,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:  # fmt: skip
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds)
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}

    async def extract(self, resume_ref: uuid.UUID, file: bytes) -> ResumeAIData:
        """Read the resume and store its data under `resume_ref` (replacing any earlier one)."""
        response = await self._send(
            "POST",
            _RESUMES_PATH,
            data={"candidate_id": str(resume_ref), "resume_id": RESUME_ID},
            # ResumeAI detects the type from the content, so the file name doesn't matter.
            files={"file": ("resume", file)},
        )
        try:
            return ResumeAIExtractResponse.model_validate_json(response.content).data
        except ValidationError as exc:
            logger.warning("resumeai_bad_response", operation="extract")
            raise ResumeServiceFailedError(
                "The resume service sent an answer we can't read."
            ) from exc

    async def formatted_pdf(self, resume_ref: uuid.UUID) -> bytes:
        path = f"{_RESUMES_PATH}/{quote(str(resume_ref), safe='')}/{RESUME_ID}/pdf"
        response = await self._send("GET", path, params={"template_id": TEMPLATE_ID})
        return response.content

    async def _send(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes]] | None = None,
        params: dict[str, int] | None = None,
    ) -> httpx2.Response:
        operation = "extract" if method == "POST" else "pdf"
        try:
            response = await self._client.request(
                method,
                self._base_url + path,
                headers=self._headers,
                data=data,
                files=files,
                params=params,
            )
        except httpx2.TimeoutException as exc:
            logger.warning("resumeai_unreachable", operation=operation, error="timeout")
            raise ResumeServiceUnavailableError(
                "The resume service took too long to answer. Try again in a minute."
            ) from exc
        except httpx2.HTTPError as exc:
            logger.warning("resumeai_unreachable", operation=operation, error=type(exc).__name__)
            raise ResumeServiceUnavailableError(
                "The resume service can't be reached. Try again in a minute."
            ) from exc
        if response.is_success:
            return response
        # Status only: ResumeAI's error bodies can quote the resume.
        logger.warning("resumeai_error", operation=operation, status=response.status_code)
        raise _error_for(response)

    async def aclose(self) -> None:
        await self._client.aclose()


def _detail(response: httpx2.Response) -> str | None:
    """ResumeAI's own sentence for its errors; FastAPI's field lists aren't shown to people."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    return detail if isinstance(detail, str) and len(detail) <= 300 else None


def _error_for(response: httpx2.Response) -> Exception:
    match response.status_code:
        case 401:
            return ResumeServiceUnavailableError(
                "The resume service rejected our key. Ask an admin to check RESUMEAI_API_KEY."
            )
        case 402:
            return ResumeServiceUnavailableError(
                "Reading resumes is paused right now. Fill in the form yourself."
            )
        case 404:
            return NotFoundError("The resume service has no resume stored for this candidate.")
        case 413:
            return ResumeFileTooLargeError("The file is too large. Upload one under 4 MB.")
        case 415:
            return UnsupportedResumeFileError("Upload a PDF, Word (DOC or DOCX) or text file.")
        case 422:
            return UnreadableResumeError(_detail(response) or _UNREADABLE)
        case 429:
            retry_after = response.headers.get("Retry-After", "")
            return ResumeServiceBusyError(
                "The resume service is busy. Try again in a few minutes.",
                headers={"Retry-After": retry_after} if retry_after.isdigit() else None,
            )
        case _:
            return ResumeServiceFailedError("The resume service failed. Try again in a minute.")


_installed_client: ResumeAIClient | None = None


def get_resumeai_client() -> ResumeAIClient:
    global _installed_client
    if _installed_client is None:
        settings = get_settings()
        api_key = settings.usable_resumeai_api_key()
        if api_key is None:
            raise ResumeServiceUnavailableError("Resume upload isn't set up on this server yet.")
        _installed_client = ResumeAIClient(
            api_key=api_key,
            base_url=settings.resumeai_base_url,
            timeout_seconds=settings.resumeai_timeout_seconds,
        )
    return _installed_client


def use_resumeai_client(client: ResumeAIClient | None) -> None:
    """Install a client (tests) or clear the slot, without closing what was there."""
    global _installed_client
    _installed_client = client


async def close_resumeai_client() -> None:
    global _installed_client
    if _installed_client is not None:
        await _installed_client.aclose()
        _installed_client = None
