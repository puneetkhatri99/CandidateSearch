"""saved_searches and saved_search_matches: each person's search history with its results

Revision ID: a9c4e2d7f1b3
Revises: f3b8d1a6c2e4
Create Date: 2026-11-02 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a9c4e2d7f1b3"
down_revision: str | Sequence[str] | None = "f3b8d1a6c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "saved_searches",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checked", sa.Integer(), nullable=False),
        sa.Column("ranked_by", sa.String(length=10), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("ranking_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("starred", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_searches_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_searches")),
    )
    op.create_index(
        "ix_saved_searches_user_id_created_at",
        "saved_searches",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "saved_search_matches",
        sa.Column("saved_search_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.String(length=20), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("fit", sa.String(length=10), nullable=True),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failed_filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_saved_search_matches_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["saved_search_id"],
            ["saved_searches.id"],
            name=op.f("fk_saved_search_matches_saved_search_id_saved_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_search_matches")),
    )
    op.create_index(
        op.f("ix_saved_search_matches_candidate_id"),
        "saved_search_matches",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_saved_search_matches_saved_search_id"),
        "saved_search_matches",
        ["saved_search_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_saved_search_matches_saved_search_id"), table_name="saved_search_matches"
    )
    op.drop_index(op.f("ix_saved_search_matches_candidate_id"), table_name="saved_search_matches")
    op.drop_table("saved_search_matches")
    op.drop_index("ix_saved_searches_user_id_created_at", table_name="saved_searches")
    op.drop_table("saved_searches")
