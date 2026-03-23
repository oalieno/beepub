"""Rename book_summary_embeddings to book_embeddings and add source column.

The table now holds both summary-derived and chunk-average embeddings.
source = 'summary' (from concatenated chapter summaries) or 'chunk_avg' (from AVG of chunk vectors).

Revision ID: 023
Revises: 022
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("book_summary_embeddings", "book_embeddings")
    op.add_column(
        "book_embeddings",
        sa.Column("source", sa.String(20), nullable=False, server_default="summary"),
    )


def downgrade() -> None:
    op.drop_column("book_embeddings", "source")
    op.rename_table("book_embeddings", "book_summary_embeddings")
