"""drop embedding queues

The stale scan (document hash vs stored embedding hash) now finds the work, and AI calls are
recorded once after they finish, so the queue tables and the `reserved` status are gone.

Revision ID: 0c5e9a2d7b14
Revises: f1b9d3c64e27
Create Date: 2026-10-30 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c5e9a2d7b14"
down_revision: str | Sequence[str] | None = "f1b9d3c64e27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, entity column, referenced table)
_QUEUES = (
    ("embedding_jobs", "candidate_id", "candidates"),
    ("job_embedding_queue", "job_id", "jobs"),
)


def upgrade() -> None:
    """Upgrade schema."""
    for table, _, _ in _QUEUES:
        op.drop_index(f"ix_{table}_run_after", table_name=table)
        op.drop_table(table)
    # A reservation that never settled may have been billed: keep its estimate as spent.
    op.execute(
        "UPDATE ai_usage_events SET status = 'failed', error = 'abandoned', updated_at = now() "
        "WHERE status = 'reserved'"
    )


def downgrade() -> None:
    """Downgrade schema. The queues come back empty; the old stale scan refills them."""
    for table, entity, referenced in _QUEUES:
        op.create_table(
            table,
            sa.Column(entity, sa.Uuid(), nullable=False),
            sa.Column("generation", sa.Integer(), server_default=sa.text("1"), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column(
                "run_after",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
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
            sa.ForeignKeyConstraint(
                [entity],
                [f"{referenced}.id"],
                name=op.f(f"fk_{table}_{entity}_{referenced}"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
            sa.UniqueConstraint(entity, name=f"uq_{table}_{entity}"),
        )
        op.create_index(f"ix_{table}_run_after", table, ["run_after"], unique=False)
