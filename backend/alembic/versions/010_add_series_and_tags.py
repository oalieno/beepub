"""add series and tags to books

Revision ID: 010
Revises: 009
Create Date: 2024-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("epub_series", sa.String(500), nullable=True))
    op.add_column("books", sa.Column("epub_series_index", sa.Float, nullable=True))
    op.add_column("books", sa.Column("epub_tags", ARRAY(sa.String), nullable=True))
    op.add_column("books", sa.Column("series", sa.String(500), nullable=True))
    op.add_column("books", sa.Column("series_index", sa.Float, nullable=True))
    op.add_column("books", sa.Column("tags", ARRAY(sa.String), nullable=True))
    op.create_index(
        "ix_books_epub_tags", "books", ["epub_tags"], postgresql_using="gin"
    )
    op.create_index("ix_books_tags", "books", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_books_tags", table_name="books")
    op.drop_index("ix_books_epub_tags", table_name="books")
    op.drop_column("books", "tags")
    op.drop_column("books", "series_index")
    op.drop_column("books", "series")
    op.drop_column("books", "epub_tags")
    op.drop_column("books", "epub_series_index")
    op.drop_column("books", "epub_series")
