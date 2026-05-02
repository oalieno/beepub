"""Add books.epub_mtime to detect Calibre EPUB edits.

Revision ID: 035
Revises: 034
Create Date: 2026-05-02
"""

import sqlalchemy as sa

from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column("epub_mtime", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("books", "epub_mtime")
