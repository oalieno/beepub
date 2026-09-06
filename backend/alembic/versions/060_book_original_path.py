"""Keep the uploaded source file of converted books

Books uploaded in a non-EPUB format (TXT first) are converted to an EPUB
at ingest and that EPUB is the book's file_path: every consumer (reader,
text extraction, digest, OPDS, downloads to the app) stays EPUB-only.
The source file is kept at original_path for download.

Revision ID: 060
Revises: 059
"""

import sqlalchemy as sa

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "books", sa.Column("original_path", sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("books", "original_path")
