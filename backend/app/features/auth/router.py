from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.rate_limit import client_ip, failure_slot, rate_limit_key
from app.features.auth import service
from app.features.auth.dependencies import (
    OptionalSessionUser,
    SessionUser,
    require_fetch_header,
    session_ttl,
    set_session_cookie,
)
from app.features.auth.exceptions import InvalidCredentialsError, InvalidCurrentPasswordError
from app.features.auth.schemas import ChangePasswordRequest, LoginRequest, StaffUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", dependencies=[Depends(require_fetch_header)])
async def login(
    payload: LoginRequest, request: Request, response: Response, session: SessionDep
) -> StaffUser:
    settings = get_settings()
    ip = client_ip(request)
    email = payload.email.lower()
    message = "Too many failed sign-in attempts. Try again later."
    # Only failures count, so a user who mistypes once isn't locked out by later successes.
    # The second, higher limit is per account across all IPs.
    async with (
        failure_slot(
            session,
            rate_limit_key("login_failure", email, ip),
            limit=settings.login_failure_limit,
            window_seconds=settings.login_failure_window_seconds,
            message=message,
            counts_as_failure=(InvalidCredentialsError,),
        ),
        failure_slot(
            session,
            rate_limit_key("login_failure_account", email),
            limit=settings.login_account_failure_limit,
            window_seconds=settings.login_failure_window_seconds,
            message=message,
            counts_as_failure=(InvalidCredentialsError,),
        ),
    ):
        token, user = await service.authenticate(
            session,
            email=payload.email,
            password=payload.password,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
            ttl=session_ttl(settings),
        )

    set_session_cookie(response, token, settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, session: SessionDep, actor: OptionalSessionUser
) -> None:
    """Idempotent: an expired, unknown or missing session still gets 204 and a cleared cookie."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    await service.logout(session, token, actor)
    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/me")
async def me(actor: SessionUser) -> StaffUser:
    return actor.to_staff_user()


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest, request: Request, session: SessionDep, actor: SessionUser
) -> StaffUser:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name, "")
    # Only wrong current passwords count, so a stolen session can't brute-force the password.
    async with failure_slot(
        session,
        rate_limit_key("password_change_failure", str(actor.user_id)),
        limit=settings.login_failure_limit,
        window_seconds=settings.login_failure_window_seconds,
        message="Too many failed attempts. Try again later.",
        counts_as_failure=(InvalidCurrentPasswordError,),
    ):
        return await service.change_password(session, actor, token, payload)
