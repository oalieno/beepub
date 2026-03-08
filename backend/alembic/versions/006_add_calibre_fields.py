"""add calibre fields

Revision ID: 006
Revises: 005
Create Date: 2024-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # libraries: add calibre_path (nullable, unique)
    op.add_column(
        "libraries",
        sa.Column("calibre_path", sa.String(500), nullable=True, unique=True),
    )

    # books: add calibre_id (nullable, indexed)
    op.add_column(
        "books",
        sa.Column("calibre_id", sa.Integer, nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column("books", "calibre_id")
    op.drop_column("libraries", "calibre_path")
