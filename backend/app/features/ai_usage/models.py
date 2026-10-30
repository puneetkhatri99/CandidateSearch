import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TimestampedModel


class AiUsageEvent(TimestampedModel):
    """One metered AI request. Holds counts and cost only: never text, candidate IDs or PII."""

    __tablename__ = "ai_usage_events"

    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(50))
    trigger: Mapped[str] = mapped_column(String(30))
    item_count: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # The actual cost; 0 for blocked, and for failed unless the provider billed the request.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        Index("ix_ai_usage_events_created_at", "created_at"),
        Index("ix_ai_usage_events_model", "model"),
        Index("ix_ai_usage_events_operation", "operation"),
        Index("ix_ai_usage_events_status", "status"),
    )


class AiBudget(TimestampedModel):
    """Single-row lifetime spending limit."""

    __tablename__ = "ai_budget"

    limit_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
