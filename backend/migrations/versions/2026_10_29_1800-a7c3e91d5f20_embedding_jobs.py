"""embedding jobs

Revision ID: a7c3e91d5f20
Revises: e8b2d4f61a37
Create Date: 2026-10-29 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e91d5f20"
down_revision: str | Sequence[str] | None = "e8b2d4f61a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "embedding_jobs",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
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
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_embedding_jobs_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_jobs")),
        sa.UniqueConstraint("candidate_id", name="uq_embedding_jobs_candidate_id"),
    )
    op.create_index("ix_embedding_jobs_run_after", "embedding_jobs", ["run_after"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_embedding_jobs_run_after", table_name="embedding_jobs")
    op.drop_table("embedding_jobs")
