"""candidate_bookmarks: one shared team bookmark per candidate

Revision ID: e7a1c3f5b9d2
Revises: d2b7e4a1c9f6
Create Date: 2026-11-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c3f5b9d2"
down_revision: str | Sequence[str] | None = "d2b7e4a1c9f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "candidate_bookmarks",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=False),
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
            ["added_by"],
            ["users.id"],
            name=op.f("fk_candidate_bookmarks_added_by_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_candidate_bookmarks_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_bookmarks")),
        sa.UniqueConstraint("candidate_id", name=op.f("uq_candidate_bookmarks_candidate_id")),
    )
    op.create_index(
        op.f("ix_candidate_bookmarks_added_by"), "candidate_bookmarks", ["added_by"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_candidate_bookmarks_added_by"), table_name="candidate_bookmarks")
    op.drop_table("candidate_bookmarks")
