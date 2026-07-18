"""Physical (file-less) books

A physical book is a Book row that tracks a paper copy: metadata,
reading status, rating, notes — everything interaction-level — with no
EPUB behind it. file_path/file_size become nullable; format="physical"
marks the rows. File-dependent surfaces (reader, download, OPDS
acquisition, text/embedding jobs, kosync digests) all gate on
file_path being present.

Revision ID: 053
Revises: 052
"""

import sqlalchemy as sa

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "books", "file_path", existing_type=sa.String(500), nullable=True
    )
    op.alter_column(
        "books", "file_size", existing_type=sa.BigInteger(), nullable=True
    )


def downgrade() -> None:
    # File-less rows cannot survive the NOT NULL constraints coming back.
    op.execute("DELETE FROM books WHERE file_path IS NULL")
    op.execute("UPDATE books SET file_size = 0 WHERE file_size IS NULL")
    op.alter_column(
        "books", "file_size", existing_type=sa.BigInteger(), nullable=False
    )
    op.alter_column(
        "books", "file_path", existing_type=sa.String(500), nullable=False
    )
