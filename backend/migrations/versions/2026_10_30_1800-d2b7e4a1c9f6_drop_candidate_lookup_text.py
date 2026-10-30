"""drop candidates.lookup_text: the staff name/email lookup it served is no longer used

Revision ID: d2b7e4a1c9f6
Revises: c4d8e2f6a913
Create Date: 2026-10-30 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2b7e4a1c9f6"
down_revision: str | Sequence[str] | None = "c4d8e2f6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(
        "ix_candidates_lookup_text_trgm",
        table_name="candidates",
        postgresql_using="gin",
        postgresql_ops={"lookup_text": "gin_trgm_ops"},
    )
    op.drop_column("candidates", "lookup_text")


def downgrade() -> None:
    """Downgrade schema. Rebuilds the column from the profile, as the original migration did."""
    op.add_column("candidates", sa.Column("lookup_text", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE candidates SET lookup_text = lower(regexp_replace(
            concat_ws(' ', full_name, email, headline, city, array_to_string(skills, ' ')),
            '\\s+', ' ', 'g'))
        """
    )
    op.alter_column("candidates", "lookup_text", nullable=False)
    op.create_index(
        "ix_candidates_lookup_text_trgm",
        "candidates",
        ["lookup_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"lookup_text": "gin_trgm_ops"},
    )
