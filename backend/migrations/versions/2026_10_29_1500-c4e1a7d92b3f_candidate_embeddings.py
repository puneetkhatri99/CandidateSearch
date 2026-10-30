"""candidate embeddings and embedding failures

Revision ID: c4e1a7d92b3f
Revises: ab5223c6b5bb
Create Date: 2026-10-29 15:00:00.000000

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op


class Vector(sa.types.UserDefinedType[list[float]]):
    """Local copy so this migration keeps working if the app's type changes."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimensions})"


# revision identifiers, used by Alembic.
revision: str = "c4e1a7d92b3f"
down_revision: str | Sequence[str] | None = "ab5223c6b5bb"
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
    # Needs pgvector >= 0.8.0 installed on the server (Phase 4 relies on iterative scans).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "candidate_embeddings",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_candidate_embeddings_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_embeddings")),
        sa.UniqueConstraint(
            "candidate_id", "model", name="uq_candidate_embeddings_candidate_id_model"
        ),
    )
    op.create_index(
        "ix_candidate_embeddings_embedding_hnsw",
        "candidate_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "embedding_failures",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_embedding_failures_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_failures")),
        sa.UniqueConstraint(
            "candidate_id", "model", name="uq_embedding_failures_candidate_id_model"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("embedding_failures")
    op.drop_index(
        "ix_candidate_embeddings_embedding_hnsw",
        table_name="candidate_embeddings",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("candidate_embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
