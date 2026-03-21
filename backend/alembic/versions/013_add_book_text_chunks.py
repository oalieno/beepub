"""add book_text_chunks table for pre-extracted EPUB text

Revision ID: 013
Revises: 012
Create Date: 2024-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "book_text_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("spine_index", sa.Integer, nullable=False),
        sa.Column("section_title", sa.String(500), nullable=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("char_offset", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("book_id", "spine_index", name="uq_book_text_chunk_book_spine"),
    )


def downgrade() -> None:
    op.drop_table("book_text_chunks")
