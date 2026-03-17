"""add word_count to books

Revision ID: 009
Revises: 008
Create Date: 2024-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column("word_count", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("books", "word_count")
