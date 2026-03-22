"""add book_embedding_chunks table with pgvector

Revision ID: 015
Revises: 014
Create Date: 2026-03-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "book_embedding_chunks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "book_text_chunk_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("book_text_chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("spine_index", sa.Integer, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("char_offset_start", sa.Integer, nullable=False),
        sa.Column("char_offset_end", sa.Integer, nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Unique constraint for idempotent embedding
    op.create_unique_constraint(
        "uq_embedding_chunk_text_chunk_idx",
        "book_embedding_chunks",
        ["book_text_chunk_id", "chunk_index"],
    )


def downgrade() -> None:
    op.drop_table("book_embedding_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
