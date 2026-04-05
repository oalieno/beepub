"""Add auto_sync and last_synced_at columns to libraries.

Revision ID: 028
Revises: 027
Create Date: 2026-04-05
"""

import sqlalchemy as sa

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "libraries",
        sa.Column(
            "auto_sync", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "libraries",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("libraries", "last_synced_at")
    op.drop_column("libraries", "auto_sync")
