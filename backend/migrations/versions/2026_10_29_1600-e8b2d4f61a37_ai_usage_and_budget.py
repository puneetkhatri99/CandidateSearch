"""ai usage events and budget

Revision ID: e8b2d4f61a37
Revises: c4e1a7d92b3f
Create Date: 2026-10-29 16:00:00.000000

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b2d4f61a37"
down_revision: str | Sequence[str] | None = "c4e1a7d92b3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_usage_events",
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage_events")),
    )
    op.create_index("ix_ai_usage_events_created_at", "ai_usage_events", ["created_at"])
    op.create_index("ix_ai_usage_events_model", "ai_usage_events", ["model"])
    op.create_index("ix_ai_usage_events_operation", "ai_usage_events", ["operation"])
    op.create_index("ix_ai_usage_events_status", "ai_usage_events", ["status"])

    op.create_table(
        "ai_budget",
        sa.Column("limit_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_ai_budget_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_budget")),
    )
    op.create_index(op.f("ix_ai_budget_updated_by"), "ai_budget", ["updated_by"])
    # Default lifetime limit; admins change it from the AI spending page.
    op.execute("INSERT INTO ai_budget (id, limit_usd) VALUES (gen_random_uuid(), 5.00)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_ai_budget_updated_by"), table_name="ai_budget")
    op.drop_table("ai_budget")
    op.drop_index("ix_ai_usage_events_status", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_operation", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_model", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_created_at", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
