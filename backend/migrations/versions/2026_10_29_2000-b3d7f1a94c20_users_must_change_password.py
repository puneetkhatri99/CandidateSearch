"""users must change password

Revision ID: b3d7f1a94c20
Revises: a7c3e91d5f20
Create Date: 2026-10-29 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d7f1a94c20"
down_revision: str | Sequence[str] | None = "a7c3e91d5f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing users chose their own password (or the operator did), so they start unflagged.
    op.add_column(
        "users",
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "must_change_password")
