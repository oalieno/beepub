"""Drop bookshelves.is_public column.

Revision ID: 033
Revises: 032
Create Date: 2026-04-10
"""

import sqlalchemy as sa

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("bookshelves", "is_public")


def downgrade() -> None:
    op.add_column(
        "bookshelves",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
