"""Base exception types and handlers that render the standard error body:

{"error": {"code": "...", "message": "...", "details": {...}}}
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base for all expected, client-facing errors. Features subclass this."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class NotAuthenticatedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


def describe_error(exc: BaseException) -> str:
    """Error class plus HTTP status only: safe to store, never contains input text."""
    status_code = getattr(exc, "status_code", None)
    name = type(exc).__name__
    return f"{name} status={status_code}"[:200] if status_code else name[:200]


# Framework-raised HTTP errors that deserve a specific machine-readable code.
_HTTP_ERROR_CODES = {status.HTTP_413_CONTENT_TOO_LARGE: "payload_too_large"}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
        headers=headers,
    )


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - narrowing for the registered type
    return _error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    # Only loc/msg/type: raw errors can hold non-JSON values and echo the submitted input.
    errors = [
        {"loc": list(err["loc"]), "msg": str(err["msg"]), "type": str(err["type"])}
        for err in exc.errors()
    ]
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Request validation failed.",
        {"errors": errors},
    )


async def _handle_http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return _error_response(exc.status_code, code, str(exc.detail))


class UnhandledErrorMiddleware:
    """Turns any unexpected exception into the standard 500 body.

    It sits inside CORS and request-context middleware, so the 500 carries CORS headers and
    X-Request-ID and is logged as a normal request. Starlette's own Exception handler runs in
    the outermost layer, after all of those were bypassed.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # CancelledError is a BaseException and still propagates
            logger.exception("unhandled_error", error_type=type(exc).__name__)
            if started:
                raise  # headers are already sent; nothing valid can be written
            response = _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "internal_error",
                "An unexpected error occurred.",
            )
            await response(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
