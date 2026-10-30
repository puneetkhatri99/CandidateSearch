from typing import Any

from fastapi import status

from app.core.errors import AppError, ConflictError, NotFoundError


class JobNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("Job not found.")


class JobVersionConflictError(ConflictError):
    code = "version_conflict"

    def __init__(self) -> None:
        super().__init__("This job was changed by someone else. Reload to see the latest version.")


class JobValidationError(AppError):
    """An edit whose merged result breaks a rule; shaped like FastAPI's own 422 body."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("Request validation failed.", {"errors": errors})
