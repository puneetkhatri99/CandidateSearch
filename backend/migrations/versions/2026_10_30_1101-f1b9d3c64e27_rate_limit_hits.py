"""rate limit hits

Revision ID: f1b9d3c64e27
Revises: e4a8c2b71f05
Create Date: 2026-10-30 11:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b9d3c64e27"
down_revision: str | Sequence[str] | None = "e4a8c2b71f05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "rate_limit_hits",
        sa.Column("id", sa.Uuid(), nullable=False),
        # "<scope>:<hmac hex>", never raw emails, IPs or ids.
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_limit_hits")),
    )
    op.create_index("ix_rate_limit_hits_key_created_at", "rate_limit_hits", ["key", "created_at"])
    op.create_index(op.f("ix_rate_limit_hits_expires_at"), "rate_limit_hits", ["expires_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_rate_limit_hits_expires_at"), table_name="rate_limit_hits")
    op.drop_index("ix_rate_limit_hits_key_created_at", table_name="rate_limit_hits")
    op.drop_table("rate_limit_hits")
