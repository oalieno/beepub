"""Enforce 1:N: a book lives in exactly one library.

Revision ID: 036
Revises: 035
Create Date: 2026-05-06
"""

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_library_books_book_id", "library_books", ["book_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_library_books_book_id", "library_books", type_="unique")
