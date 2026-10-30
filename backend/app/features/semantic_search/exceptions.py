from fastapi import status

from app.core.errors import AppError


class QueryLooksPersonalError(AppError):
    """The query looks like an email, phone number or URL, which must not be sent to OpenAI."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "query_not_searchable_by_meaning"


class SemanticSearchUnavailableError(AppError):
    """No API key, or OpenAI failed or timed out. Browsing by filters still works."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "semantic_search_unavailable"


class JobNotReadyForMatchingError(AppError):
    """The job has no embedding of its current text yet (just saved, failed, or no budget)."""

    status_code = status.HTTP_409_CONFLICT
    code = "job_not_ready_for_matching"
