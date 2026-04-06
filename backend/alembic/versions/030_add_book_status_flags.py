"""Add per-book job status flags to eliminate expensive subqueries.

Revision ID: 030
Revises: 029
Create Date: 2026-04-06
"""

import sqlalchemy as sa

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add columns with server defaults (no table rewrite needed)
    op.add_column(
        "books",
        sa.Column(
            "has_text", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "is_summarized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "has_embedding",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "has_tags", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "metadata_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # 2. Backfill from existing data
    op.execute("""
        UPDATE books SET has_text = true
        WHERE EXISTS (
            SELECT 1 FROM book_text_chunks WHERE book_text_chunks.book_id = books.id
        )
    """)

    op.execute("""
        UPDATE books SET is_summarized = true
        WHERE has_text = true
          AND NOT EXISTS (
            SELECT 1 FROM book_text_chunks
            WHERE book_text_chunks.book_id = books.id
              AND book_text_chunks.summary IS NULL
        )
    """)

    op.execute("""
        UPDATE books SET has_embedding = true
        WHERE EXISTS (
            SELECT 1 FROM book_embeddings WHERE book_embeddings.book_id = books.id
        )
    """)

    op.execute("""
        UPDATE books SET has_tags = true
        WHERE EXISTS (
            SELECT 1 FROM book_tags WHERE book_tags.book_id = books.id
        )
    """)

    op.execute("""
        UPDATE books SET metadata_count = sub.cnt
        FROM (
            SELECT book_id, COUNT(DISTINCT source) AS cnt
            FROM external_metadata
            GROUP BY book_id
        ) sub
        WHERE books.id = sub.book_id
    """)

    # 3. Add indexes for fast job status counts
    op.create_index("ix_books_has_text", "books", ["has_text"])
    op.create_index("ix_books_is_summarized", "books", ["is_summarized"])
    op.create_index("ix_books_has_embedding", "books", ["has_embedding"])
    op.create_index("ix_books_has_tags", "books", ["has_tags"])
    op.create_index("ix_books_metadata_count", "books", ["metadata_count"])

    # 4. Drop partial index that is no longer needed (replaced by is_summarized flag)
    op.drop_index("ix_book_text_chunks_unsummarized", table_name="book_text_chunks")


def downgrade() -> None:
    # Restore the partial index
    op.create_index(
        "ix_book_text_chunks_unsummarized",
        "book_text_chunks",
        ["book_id"],
        postgresql_where="summary IS NULL",
    )

    op.drop_index("ix_books_metadata_count", table_name="books")
    op.drop_index("ix_books_has_tags", table_name="books")
    op.drop_index("ix_books_has_embedding", table_name="books")
    op.drop_index("ix_books_is_summarized", table_name="books")
    op.drop_index("ix_books_has_text", table_name="books")

    op.drop_column("books", "metadata_count")
    op.drop_column("books", "has_tags")
    op.drop_column("books", "has_embedding")
    op.drop_column("books", "is_summarized")
    op.drop_column("books", "has_text")
