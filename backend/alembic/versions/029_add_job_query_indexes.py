"""Add indexes to speed up job status queries.

Revision ID: 029
Revises: 028
Create Date: 2026-04-06
"""

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Book.is_image_book — used by 4 job types to filter missing/blocked counts
    op.create_index("ix_books_is_image_book", "books", ["is_image_book"])

    # BookTextChunk.summary IS NULL — used by summarize + book_embedding jobs
    # Partial index: only index rows where summary IS NULL (the ones we query for)
    op.create_index(
        "ix_book_text_chunks_unsummarized",
        "book_text_chunks",
        ["book_id"],
        postgresql_where="summary IS NULL",
    )


def downgrade() -> None:
    op.drop_index("ix_book_text_chunks_unsummarized", table_name="book_text_chunks")
    op.drop_index("ix_books_is_image_book", table_name="books")
