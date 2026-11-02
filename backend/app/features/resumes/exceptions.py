from fastapi import status

from app.core.errors import AppError


class ResumeServiceUnavailableError(AppError):
    """No key, a refused key, paused uploads, or ResumeAI not answering."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "resume_service_unavailable"


class ResumeServiceFailedError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "resume_service_failed"


class ResumeFileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"


class UnsupportedResumeFileError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_file"


class UnreadableResumeError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "resume_unreadable"


class ResumeServiceBusyError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
