"""candidates search_tsv

Revision ID: a7c3e9d51b28
Revises: 0c5e9a2d7b14
Create Date: 2026-10-30 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7c3e9d51b28"
down_revision: str | Sequence[str] | None = "0c5e9a2d7b14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # A stored generated column rewrites candidates once (about a second at 1,000 rows).
    op.add_column(
        "candidates",
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            # Copied, not imported: a migration must not change when the model does.
            sa.Computed(
                "to_tsvector('english'::regconfig, search_document || ' ' || city)",
                persisted=True,
            ),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_candidates_search_tsv", "candidates", ["search_tsv"], postgresql_using="gin"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_candidates_search_tsv", table_name="candidates", postgresql_using="gin")
    op.drop_column("candidates", "search_tsv")
