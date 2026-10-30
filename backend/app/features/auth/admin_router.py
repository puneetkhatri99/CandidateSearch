"""Staff account management. Admin only; the service re-checks the role."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.rate_limit import acquire_slot, rate_limit_key
from app.features.auth import service
from app.features.auth.dependencies import AdminUser
from app.features.auth.schemas import (
    CreateUserRequest,
    ResetPasswordRequest,
    UpdateUserRequest,
    UserAccount,
    UserAccountPage,
    UserListParams,
)

router = APIRouter(prefix="/admin/users", tags=["admin: users"])


async def limit_account_writes(session: SessionDep, actor: AdminUser) -> None:
    """Per-admin limit on the two routes that run argon2 (checked after the role check)."""
    settings = get_settings()
    await acquire_slot(
        session,
        rate_limit_key("admin_account_write", str(actor.user_id)),
        limit=settings.admin_account_write_limit,
        window_seconds=settings.admin_account_write_window_seconds,
        message="Too many account changes. Try again later.",
    )


@router.get("")
async def list_users(
    params: Annotated[UserListParams, Query()], session: SessionDep, actor: AdminUser
) -> UserAccountPage:
    return await service.list_users(session, actor, params)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(limit_account_writes)])
async def create_user(
    payload: CreateUserRequest, session: SessionDep, actor: AdminUser
) -> UserAccount:
    return await service.create_user_by_admin(session, actor, payload)


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID, payload: UpdateUserRequest, session: SessionDep, actor: AdminUser
) -> UserAccount:
    return await service.update_user(session, actor, user_id, payload)


@router.post("/{user_id}/reset-password", dependencies=[Depends(limit_account_writes)])
async def reset_password(
    user_id: uuid.UUID, payload: ResetPasswordRequest, session: SessionDep, actor: AdminUser
) -> UserAccount:
    return await service.reset_password(session, actor, user_id, payload)
