"""candidates.resume_pdf_key: where the stored copy of the formatted resume PDF lives

Revision ID: b5e2c8a4d7f1
Revises: a9c4e2d7f1b3
Create Date: 2026-11-02 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e2c8a4d7f1"
down_revision: str | Sequence[str] | None = "a9c4e2d7f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("candidates", sa.Column("resume_pdf_key", sa.String(length=300), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("candidates", "resume_pdf_key")
