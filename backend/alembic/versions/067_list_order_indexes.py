"""Indexes for the orders and lookups the lists actually use

The book list sorted by title orders on the title shown — an expression
over two columns, which had no index, so every page sorted the whole
table (and "open the page on this book" sorted it again to find one
row). A library's newest books, for the cards on
the libraries page, were found by ranking every book of every library.

Revision ID: 067
Revises: 066
"""

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_books_display_title ON books ((coalesce(title, epub_title)))"
    )
    op.execute(
        "CREATE INDEX ix_library_books_library_added "
        "ON library_books (library_id, added_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_library_books_library_added")
    op.execute("DROP INDEX ix_books_display_title")
