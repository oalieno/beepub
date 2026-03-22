"""Add pg_trgm extension and GIN index on book_embedding_chunks.text for keyword search.

Revision ID: 018
"""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX idx_book_embedding_chunks_text_trgm "
        "ON book_embedding_chunks USING gin (text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_book_embedding_chunks_text_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
