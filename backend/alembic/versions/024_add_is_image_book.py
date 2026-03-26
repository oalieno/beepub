"""Add is_image_book boolean column to books table.

Nullable column, no default — zero-downtime (no table rewrite in PostgreSQL).

Revision ID: 024
Revises: 023
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("is_image_book", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "is_image_book")
