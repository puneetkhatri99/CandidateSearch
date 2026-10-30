"""candidate expected salary and job pay range

Revision ID: c4d8e2f6a913
Revises: a7c3e9d51b28
Create Date: 2026-10-30 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8e2f6a913"
down_revision: str | Sequence[str] | None = "a7c3e9d51b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable columns with no default: metadata-only, no table rewrite.
    op.add_column("candidates", sa.Column("expected_salary", sa.Integer(), nullable=True))
    op.add_column("candidates", sa.Column("salary_currency", sa.String(length=3), nullable=True))
    op.create_check_constraint(
        op.f("ck_candidates_expected_salary_valid"),
        "candidates",
        "(expected_salary IS NULL) = (salary_currency IS NULL)"
        " AND (expected_salary IS NULL OR expected_salary BETWEEN 1 AND 1000000000)",
    )
    op.add_column("jobs", sa.Column("salary_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_currency", sa.String(length=3), nullable=True))
    op.create_check_constraint(
        op.f("ck_jobs_salary_valid"),
        "jobs",
        "(salary_currency IS NULL) = (salary_min IS NULL AND salary_max IS NULL)"
        " AND (salary_min IS NULL OR salary_min BETWEEN 1 AND 1000000000)"
        " AND (salary_max IS NULL OR salary_max BETWEEN 1 AND 1000000000)"
        " AND (salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_jobs_salary_valid"), "jobs", type_="check")
    op.drop_column("jobs", "salary_currency")
    op.drop_column("jobs", "salary_max")
    op.drop_column("jobs", "salary_min")
    op.drop_constraint(op.f("ck_candidates_expected_salary_valid"), "candidates", type_="check")
    op.drop_column("candidates", "salary_currency")
    op.drop_column("candidates", "expected_salary")
