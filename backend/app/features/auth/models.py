import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TimestampedModel


class User(TimestampedModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set for admin-chosen temporary passwords; the API refuses everything else until changed.
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # Fetch server-generated columns (created_at) on insert; async sessions can't lazy-load them.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    __table_args__ = (CheckConstraint("role IN ('admin', 'recruiter')", name="role_valid"),)


class UserSession(TimestampedModel):
    """Server-side session. Only a hash of the cookie token is stored."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
