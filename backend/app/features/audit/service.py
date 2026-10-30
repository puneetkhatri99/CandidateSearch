import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.audit.models import AuditEvent

AuditAction = Literal[
    "auth.login",
    "auth.logout",
    "auth.password_change",
    "user.create",
    "user.update",
    "user.password_reset",
    "job.create",
    "job.update",
    "job.match",
    "candidate.view",
    "candidate.search",
    "candidate.create",
    "candidate.update",
    "candidate.delete",
    "ai_budget.update",
]


def record_event(
    session: AsyncSession,
    *,
    action: AuditAction,
    entity_type: str,
    entity_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    ip: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit event to the caller's transaction, so it commits or rolls back with it."""
    session.add(
        AuditEvent(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            ip=ip,
            details=details or {},
        )
    )
