"""Fix book_text_chunks unique constraint to include char_offset.

The original constraint (book_id, spine_index) was too narrow — a single
spine section can produce multiple chunks with different char_offsets.

Revision ID: 018
Revises: 017
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_book_text_chunk_book_spine", "book_text_chunks", type_="unique"
    )
    op.create_unique_constraint(
        "uq_book_text_chunk_book_spine_offset",
        "book_text_chunks",
        ["book_id", "spine_index", "char_offset"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_book_text_chunk_book_spine_offset", "book_text_chunks", type_="unique"
    )
    op.create_unique_constraint(
        "uq_book_text_chunk_book_spine",
        "book_text_chunks",
        ["book_id", "spine_index"],
    )
