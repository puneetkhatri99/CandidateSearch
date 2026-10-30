from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request, Response

from app.core.config import Settings, get_settings
from app.core.db import SessionDep
from app.core.errors import ForbiddenError, NotAuthenticatedError
from app.core.rate_limit import client_ip
from app.features.auth import service
from app.features.auth.exceptions import CsrfCheckFailedError, PasswordChangeRequiredError
from app.features.auth.schemas import AuthContext, Role

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-requested-with"
CSRF_HEADER_VALUE = "fetch"


def session_ttl(settings: Settings) -> timedelta:
    return timedelta(hours=settings.session_ttl_hours)


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=int(session_ttl(settings).total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


async def require_fetch_header(request: Request) -> None:
    """CSRF guard: a custom header can't be sent cross-site without passing CORS preflight."""
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise CsrfCheckFailedError("Missing request header. Reload the page and try again.")


async def require_fetch_header_on_any_method(request: Request) -> None:
    """For GETs that spend money: a cross-site link sends the Lax cookie, never this header."""
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise CsrfCheckFailedError("Missing request header. Reload the page and try again.")


async def get_optional_session_context(
    request: Request,
    response: Response,
    session: SessionDep,
    _: Annotated[None, Depends(require_fetch_header)],
) -> AuthContext | None:
    """The signed-in user, or None when the cookie is missing or the session is dead. No
    password-change check."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    resolved = await service.resolve_session(
        session, token, ip=client_ip(request), ttl=session_ttl(settings)
    )
    if resolved is None:
        return None
    context, extended = resolved
    if extended:
        set_session_cookie(response, token, settings)
    return context


async def get_session_context(
    request: Request,
    context: Annotated[AuthContext | None, Depends(get_optional_session_context)],
) -> AuthContext:
    """The signed-in user, with no password-change check. Only for the routes that must work
    while a change is pending (see `SessionUser`)."""
    if context is None:
        if request.cookies.get(get_settings().session_cookie_name):
            raise NotAuthenticatedError("Your session has ended. Please sign in again.")
        raise NotAuthenticatedError("Please sign in.")
    return context


async def get_auth_context(
    context: Annotated[AuthContext, Depends(get_session_context)],
) -> AuthContext:
    # Fail closed: every route that depends on CurrentUser is blocked until the password is
    # changed, including routes added later.
    if context.must_change_password:
        raise PasswordChangeRequiredError
    return context


CurrentUser = Annotated[AuthContext, Depends(get_auth_context)]
# Only GET /auth/me and POST /auth/change-password may use this.
SessionUser = Annotated[AuthContext, Depends(get_session_context)]
# Only POST /auth/logout: logging out must work, and clear the cookie, even for a dead session.
OptionalSessionUser = Annotated[AuthContext | None, Depends(get_optional_session_context)]


def require_role(*roles: Role) -> Callable[[AuthContext], Awaitable[AuthContext]]:
    async def dependency(context: CurrentUser) -> AuthContext:
        if context.role not in roles:
            raise ForbiddenError("You don't have permission to do this.")
        return context

    return dependency


AdminUser = Annotated[AuthContext, Depends(require_role("admin"))]
