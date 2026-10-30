"""embedding queue leases

Revision ID: e4a8c2b71f05
Revises: d9f2c5e83a16
Create Date: 2026-10-30 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4a8c2b71f05"
down_revision: str | Sequence[str] | None = "d9f2c5e83a16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QUEUES = ("embedding_jobs", "job_embedding_queue")


def upgrade() -> None:
    """Upgrade schema."""
    # run_after alone can't tell a worker's lease from transient backoff.
    for table in _QUEUES:
        op.add_column(table, sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for table in _QUEUES:
        op.drop_column(table, "leased_until")
