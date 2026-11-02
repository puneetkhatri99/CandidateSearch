"""candidates.resume_ref: the reference ResumeAI stores the candidate's resume data under

Revision ID: f3b8d1a6c2e4
Revises: e7a1c3f5b9d2
Create Date: 2026-11-02 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b8d1a6c2e4"
down_revision: str | Sequence[str] | None = "e7a1c3f5b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("candidates", sa.Column("resume_ref", sa.Uuid(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("candidates", "resume_ref")
