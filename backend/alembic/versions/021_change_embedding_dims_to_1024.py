"""Change embedding vector dimensions from 768 to 1024.

Switching from Gemini Embedding 001 (768-dim MRL) to Qwen3-Embedding-0.6B (1024-dim).
Old embeddings are incompatible — truncate both tables so they can be re-embedded.

Revision ID: 021
Revises: 020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Truncate old incompatible embeddings (different model, different dimensions)
    op.execute(sa.text("TRUNCATE TABLE book_embedding_chunks"))
    op.execute(sa.text("TRUNCATE TABLE book_summary_embeddings"))

    # Change vector dimensions: 768 → 1024
    op.alter_column(
        "book_embedding_chunks",
        "embedding",
        type_=Vector(1024),
        existing_nullable=False,
    )
    op.alter_column(
        "book_summary_embeddings",
        "embedding",
        type_=Vector(1024),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(sa.text("TRUNCATE TABLE book_embedding_chunks"))
    op.execute(sa.text("TRUNCATE TABLE book_summary_embeddings"))

    op.alter_column(
        "book_embedding_chunks",
        "embedding",
        type_=Vector(768),
        existing_nullable=False,
    )
    op.alter_column(
        "book_summary_embeddings",
        "embedding",
        type_=Vector(768),
        existing_nullable=False,
    )
