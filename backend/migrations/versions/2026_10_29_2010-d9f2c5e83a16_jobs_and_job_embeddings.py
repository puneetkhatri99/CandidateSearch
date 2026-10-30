"""jobs and job embeddings

Revision ID: d9f2c5e83a16
Revises: b3d7f1a94c20
Create Date: 2026-10-29 20:10:00.000000

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


class Vector(sa.types.UserDefinedType[list[float]]):
    """Local copy so this migration keeps working if the app's type changes."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimensions})"


# revision identifiers, used by Alembic.
revision: str = "d9f2c5e83a16"
down_revision: str | Sequence[str] | None = "b3d7f1a94c20"
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
        "jobs",
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("department", sa.String(length=120), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("work_mode", sa.String(length=10), nullable=False),
        sa.Column("employment_type", sa.String(length=20), nullable=False),
        sa.Column("min_years", sa.Numeric(precision=3, scale=1), nullable=False),
        sa.Column("max_years", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("must_have_skills", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "nice_to_have_skills",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("search_document", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "work_mode IN ('remote', 'hybrid', 'onsite')", name=op.f("ck_jobs_work_mode_valid")
        ),
        sa.CheckConstraint(
            "employment_type IN ('full_time', 'part_time', 'contract', 'internship')",
            name=op.f("ck_jobs_employment_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'closed')", name=op.f("ck_jobs_status_valid")
        ),
        sa.CheckConstraint(
            "min_years >= 0 AND min_years <= 50", name=op.f("ck_jobs_min_years_range")
        ),
        sa.CheckConstraint(
            "max_years IS NULL OR (max_years >= min_years AND max_years <= 50)",
            name=op.f("ck_jobs_max_years_range"),
        ),
        sa.CheckConstraint(
            "cardinality(must_have_skills) BETWEEN 1 AND 20",
            name=op.f("ck_jobs_must_have_skills_count"),
        ),
        sa.CheckConstraint(
            "cardinality(nice_to_have_skills) <= 20",
            name=op.f("ck_jobs_nice_to_have_skills_count"),
        ),
        sa.CheckConstraint(
            "work_mode = 'remote' OR (city IS NOT NULL AND country_code IS NOT NULL)",
            name=op.f("ck_jobs_location_required"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_jobs_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_created_by", "jobs", ["created_by"], unique=False)
    op.create_index("ix_jobs_created_at_id", "jobs", ["created_at", "id"], unique=False)

    op.create_table(
        "job_embeddings",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_embeddings_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_embeddings")),
        sa.UniqueConstraint("job_id", "model", name="uq_job_embeddings_job_id_model"),
    )
    op.create_index(
        "ix_job_embeddings_embedding_hnsw",
        "job_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "job_embedding_failures",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_embedding_failures_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_embedding_failures")),
        sa.UniqueConstraint("job_id", "model", name="uq_job_embedding_failures_job_id_model"),
    )
    op.create_table(
        "job_embedding_queue",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_embedding_queue_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_embedding_queue")),
        sa.UniqueConstraint("job_id", name="uq_job_embedding_queue_job_id"),
    )
    op.create_index(
        "ix_job_embedding_queue_run_after", "job_embedding_queue", ["run_after"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_job_embedding_queue_run_after", table_name="job_embedding_queue")
    op.drop_table("job_embedding_queue")
    op.drop_table("job_embedding_failures")
    op.drop_index(
        "ix_job_embeddings_embedding_hnsw",
        table_name="job_embeddings",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("job_embeddings")
    op.drop_index("ix_jobs_created_at_id", table_name="jobs")
    op.drop_index("ix_jobs_created_by", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
