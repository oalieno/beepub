"""Bookshelves can hold series as units; drop the obsolete user tier theme.

A bookshelf membership row now points at *either* a book or a series (by its
normalised series key), so a surrogate UUID id replaces the old
(bookshelf_id, book_id) composite primary key. The tier-list theme is now a
client-only preference, so the unused users.tier_theme column is dropped.

Revision ID: 041
Revises: 040
Create Date: 2026-06-05
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Surrogate primary key so a row can omit book_id (series rows).
    op.add_column(
        "bookshelf_books",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.execute("UPDATE bookshelf_books SET id = gen_random_uuid() WHERE id IS NULL")
    op.add_column(
        "bookshelf_books",
        sa.Column("series_key", sa.String(500), nullable=True),
    )

    # Swap the composite PK for the surrogate id. The old PK must go before
    # book_id can drop NOT NULL (a PK column can't be nullable).
    op.drop_constraint("bookshelf_books_pkey", "bookshelf_books", type_="primary")
    op.alter_column(
        "bookshelf_books", "book_id", existing_type=sa.UUID(), nullable=True
    )
    op.alter_column("bookshelf_books", "id", existing_type=sa.UUID(), nullable=False)
    op.create_primary_key("bookshelf_books_pkey", "bookshelf_books", ["id"])

    # Exactly one target per row.
    op.create_check_constraint(
        "ck_bookshelf_books_one_target",
        "bookshelf_books",
        "(book_id IS NOT NULL) <> (series_key IS NOT NULL)",
    )
    # No duplicate book / series within a shelf.
    op.create_index(
        "uq_bookshelf_books_book",
        "bookshelf_books",
        ["bookshelf_id", "book_id"],
        unique=True,
        postgresql_where=sa.text("book_id IS NOT NULL"),
    )
    op.create_index(
        "uq_bookshelf_books_series",
        "bookshelf_books",
        ["bookshelf_id", "series_key"],
        unique=True,
        postgresql_where=sa.text("series_key IS NOT NULL"),
    )

    # Tier theme now lives on the shelf, not the user.
    op.drop_column("users", "tier_theme")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tier_theme", postgresql.JSONB(), nullable=True),
    )

    op.drop_index("uq_bookshelf_books_series", table_name="bookshelf_books")
    op.drop_index("uq_bookshelf_books_book", table_name="bookshelf_books")
    op.drop_constraint(
        "ck_bookshelf_books_one_target", "bookshelf_books", type_="check"
    )

    # Drop series rows that can't exist under the old book-only schema.
    op.execute("DELETE FROM bookshelf_books WHERE book_id IS NULL")

    op.drop_constraint("bookshelf_books_pkey", "bookshelf_books", type_="primary")
    op.drop_column("bookshelf_books", "series_key")
    op.drop_column("bookshelf_books", "id")
    op.alter_column(
        "bookshelf_books", "book_id", existing_type=sa.UUID(), nullable=False
    )
    op.create_primary_key(
        "bookshelf_books_pkey", "bookshelf_books", ["bookshelf_id", "book_id"]
    )
