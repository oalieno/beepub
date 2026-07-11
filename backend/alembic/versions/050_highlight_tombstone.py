"""Highlight soft-delete tombstone

Groundwork for offline-first highlight sync (Phase 2): a deletion is an
update that must propagate to other devices, so DELETE stamps deleted_at
instead of removing the row. A future batch-sync endpoint unions tombstones
across devices; without them a sync merge resurrects deleted highlights.
Every list endpoint filters deleted_at IS NULL, so tombstones are invisible
to the API surface.

Revision ID: 050
Revises: 049
"""

import sqlalchemy as sa

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "highlights",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("highlights", "deleted_at")
