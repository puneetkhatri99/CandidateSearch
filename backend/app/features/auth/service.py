import hashlib
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.core.pagination import decode_created_at_cursor, next_created_at_cursor
from app.features.audit import record_event
from app.features.auth import passwords, repository
from app.features.auth.exceptions import (
    CannotModifySelfError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    LastAdminError,
    PasswordUnchangedError,
    UserAlreadyExistsError,
    UserNotFoundError,
    WeakPasswordError,
)
from app.features.auth.models import User, UserSession
from app.features.auth.schemas import (
    AuthContext,
    ChangePasswordRequest,
    CreateUserRequest,
    ResetPasswordRequest,
    Role,
    StaffUser,
    UpdateUserRequest,
    UserAccount,
    UserAccountPage,
    UserListParams,
)

logger = structlog.get_logger(__name__)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _role(user: User) -> Role:
    return "admin" if user.role == "admin" else "recruiter"


def _context(user: User, ip: str | None) -> AuthContext:
    return AuthContext(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=_role(user),
        ip=ip,
        must_change_password=user.must_change_password,
    )


def _staff_user(user: User) -> StaffUser:
    return _context(user, None).to_staff_user()


def _account(user: User) -> UserAccount:
    return UserAccount(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=_role(user),
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


async def authenticate(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
    ttl: timedelta,
) -> tuple[str, StaffUser]:
    """Check credentials and open a session. Returns the raw cookie token and the user."""
    async with session.begin():
        user = await repository.get_user_by_email(session, email)
        if user is None or not user.is_active:
            await passwords.burn_verification_time(password)
            raise InvalidCredentialsError
        if not await passwords.verify_password(user.password_hash, password):
            raise InvalidCredentialsError

        if passwords.needs_rehash(user.password_hash):
            user.password_hash = await passwords.hash_password(password)

        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        await repository.add_session(
            session,
            UserSession(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=now + ttl,
                last_seen_at=now,
                ip=ip,
                user_agent=(user_agent or "")[:300] or None,
            ),
        )
        user.last_login_at = now
        record_event(
            session,
            action="auth.login",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            ip=ip,
        )
        context = _context(user, ip)

    logger.info("staff_login", user_id=str(context.user_id))
    return token, context.to_staff_user()


async def resolve_session(
    session: AsyncSession, token: str, *, ip: str | None, ttl: timedelta
) -> tuple[AuthContext, bool] | None:
    """Look up a live session. Returns (context, extended) or None if invalid or expired.

    Sessions roll forward once less than half their lifetime remains, so active users stay
    signed in without a database write on every request. The role and the password-change
    flag are read from the user row each time, so changes apply to existing sessions at once.
    """
    async with session.begin():
        found = await repository.get_live_session(session, hash_token(token), datetime.now(UTC))
        if found is None:
            return None
        user_session, user = found
        now = datetime.now(UTC)
        extended = user_session.expires_at - now < ttl / 2
        if extended:
            user_session.expires_at = now + ttl
            user_session.last_seen_at = now
        return _context(user, ip), extended


async def logout(session: AsyncSession, token: str | None, actor: AuthContext | None) -> None:
    """Delete the session row (live or expired). Only a live session has an actor to audit."""
    async with session.begin():
        if token is not None:
            await repository.delete_session(session, hash_token(token))
        if actor is not None:
            record_event(
                session,
                action="auth.logout",
                entity_type="user",
                entity_id=actor.user_id,
                actor_user_id=actor.user_id,
                ip=actor.ip,
            )


SESSION_PRUNE_BATCH_SIZE = 1000


async def prune_expired_sessions(
    session: AsyncSession, *, batch_size: int = SESSION_PRUNE_BATCH_SIZE
) -> int:
    """Delete expired sessions in batches. They are already unusable; this drops stored IPs and
    user agents once the session is dead."""
    total = 0
    now = datetime.now(UTC)
    while True:
        async with session.begin():
            deleted = await repository.delete_expired_sessions(session, now, limit=batch_size)
        total += deleted
        if deleted < batch_size:
            break
    if total:
        logger.info("sessions_pruned", count=total)
    return total


def _check_password_length(password: str) -> None:
    if not passwords.MIN_PASSWORD_LENGTH <= len(password) <= passwords.MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be {passwords.MIN_PASSWORD_LENGTH} to "
            f"{passwords.MAX_PASSWORD_LENGTH} characters."
        )


async def _insert_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    role: Role,
    must_change_password: bool,
    audit_actor: AuthContext | None = None,
) -> User:
    user = User(
        email=email.strip().lower(),
        full_name=full_name.strip(),
        password_hash=await passwords.hash_password(password),
        role=role,
        is_active=True,
        must_change_password=must_change_password,
    )
    try:
        async with session.begin():
            await repository.add_user(session, user)
            if audit_actor is not None:
                record_event(
                    session,
                    action="user.create",
                    entity_type="user",
                    entity_id=user.id,
                    actor_user_id=audit_actor.user_id,
                    ip=audit_actor.ip,
                    details={"role": role},
                )
    except IntegrityError as exc:
        raise UserAlreadyExistsError("A user with this email already exists.") from exc
    return user


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    role: Role,
    must_change_password: bool = False,
) -> StaffUser:
    _check_password_length(password)
    user = await _insert_user(
        session,
        email=email,
        full_name=full_name,
        password=password,
        role=role,
        must_change_password=must_change_password,
    )
    return _staff_user(user)


async def get_full_names(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Display names for user ids, for other features to show owners. Run in the caller's
    transaction."""
    return await repository.get_full_names(session, ids)


async def change_password(
    session: AsyncSession,
    actor: AuthContext,
    token: str,
    payload: ChangePasswordRequest,
) -> StaffUser:
    """Set a new password for the signed-in user and end their other sessions."""
    if payload.new_password == payload.current_password:
        raise PasswordUnchangedError
    new_hash = await passwords.hash_password(payload.new_password)
    async with session.begin():
        user = await repository.get_user(session, actor.user_id, for_update=True)
        if user is None:
            raise UserNotFoundError
        if not await passwords.verify_password(user.password_hash, payload.current_password):
            raise InvalidCurrentPasswordError
        user.password_hash = new_hash
        user.must_change_password = False
        await repository.delete_sessions_for_user(
            session, user.id, except_token_hash=hash_token(token)
        )
        record_event(
            session,
            action="auth.password_change",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            ip=actor.ip,
        )
        result = _staff_user(user)
    logger.info("password_changed", user_id=str(actor.user_id))
    return result


# --- Admin: staff accounts ---------------------------------------------------------------


def _require_admin(actor: AuthContext) -> None:
    if not actor.is_admin:
        raise ForbiddenError("Only admins can manage staff accounts.")


async def list_users(
    session: AsyncSession, actor: AuthContext, params: UserListParams
) -> UserAccountPage:
    _require_admin(actor)
    after = decode_created_at_cursor(params.cursor)
    async with session.begin():
        rows = await repository.list_users(session, after=after, limit=params.limit)
    page, next_cursor = next_created_at_cursor(rows, params.limit)
    return UserAccountPage(items=[_account(user) for user in page], next_cursor=next_cursor)


async def create_user_by_admin(
    session: AsyncSession, actor: AuthContext, payload: CreateUserRequest
) -> UserAccount:
    _require_admin(actor)
    user = await _insert_user(
        session,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.temporary_password,
        role=payload.role,
        must_change_password=True,
        audit_actor=actor,
    )
    logger.info("user_created_by_admin", user_id=str(user.id), actor_id=str(actor.user_id))
    return _account(user)


async def update_user(
    session: AsyncSession, actor: AuthContext, user_id: uuid.UUID, payload: UpdateUserRequest
) -> UserAccount:
    _require_admin(actor)
    if user_id == actor.user_id:
        raise CannotModifySelfError("You can't change your own role or status.")
    removes_admin_rights = payload.role == "recruiter" or payload.is_active is False
    async with session.begin():
        if removes_admin_rights:
            # Serialises every change that can remove an admin; the checks below then see the
            # other admin's committed change instead of racing it.
            await repository.lock_admin_changes(session)
        user = await repository.get_user(session, user_id, for_update=True)
        if user is None:
            raise UserNotFoundError
        if (
            removes_admin_rights
            and user.role == "admin"
            and user.is_active
            and await repository.count_active_admins(session, excluding=user.id) == 0
        ):
            raise LastAdminError("There must be at least one active admin.")
        if removes_admin_rights:
            # Authorised before the lock; the actor may have been demoted while waiting for it.
            current = await repository.get_user(session, actor.user_id)
            if current is None or not (current.is_active and current.role == "admin"):
                raise ForbiddenError("Only admins can manage staff accounts.")
        changed: list[str] = []
        if payload.role is not None and payload.role != user.role:
            user.role = payload.role
            changed.append("role")
        if payload.is_active is not None and payload.is_active != user.is_active:
            user.is_active = payload.is_active
            changed.append("is_active")
            if not payload.is_active:
                # Same transaction, so a deactivated user never keeps a working session.
                await repository.delete_sessions_for_user(session, user.id)
        if changed:
            record_event(
                session,
                action="user.update",
                entity_type="user",
                entity_id=user.id,
                actor_user_id=actor.user_id,
                ip=actor.ip,
                details={
                    "changed_fields": changed,
                    "role": user.role,
                    "is_active": user.is_active,
                },
            )
        await session.flush()
        account = _account(user)
    logger.info("user_updated", user_id=str(user_id), actor_id=str(actor.user_id))
    return account


async def reset_password(
    session: AsyncSession,
    actor: AuthContext,
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
) -> UserAccount:
    _require_admin(actor)
    if user_id == actor.user_id:
        raise CannotModifySelfError("Use Change password for your own account.")
    new_hash = await passwords.hash_password(payload.temporary_password)
    async with session.begin():
        user = await repository.get_user(session, user_id, for_update=True)
        if user is None:
            raise UserNotFoundError
        user.password_hash = new_hash
        user.must_change_password = True
        await repository.delete_sessions_for_user(session, user.id)
        record_event(
            session,
            action="user.password_reset",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=actor.user_id,
            ip=actor.ip,
        )
        await session.flush()
        account = _account(user)
    logger.info("user_password_reset", user_id=str(user_id), actor_id=str(actor.user_id))
    return account
