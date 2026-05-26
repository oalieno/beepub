"""Add indexes that back the recommendation queries.

The similar-books query (services/recommendations.py) was paying for:
  * a full Seq Scan over every row in book_embeddings for the "semantic"
    nearest-neighbour lookup — there was no vector index at all, despite the
    code comment describing an HNSW ANN scan, and
  * full Seq Scans over books for author overlap (no GIN index on authors).

Add an HNSW index for cosine distance on the summary embeddings, and GIN
indexes on the author arrays so `authors && :array` overlap checks are
index-backed. (tags / epub_tags already have GIN indexes.)

Revision ID: 038
Revises: 037
"""

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HNSW index for cosine distance (the <=> operator with vector_cosine_ops).
    # Raise maintenance_work_mem for the build so the graph stays in memory
    # (otherwise it spills and takes ~20s instead of a few seconds). This is
    # session-local to the migration transaction.
    op.execute("SET maintenance_work_mem = '256MB'")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_book_embeddings_embedding_hnsw "
        "ON book_embeddings USING hnsw (embedding vector_cosine_ops)"
    )
    # GIN indexes so author-array overlap (&&) is index-backed.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_books_authors ON books USING gin (authors)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_books_epub_authors "
        "ON books USING gin (epub_authors)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_books_epub_authors")
    op.execute("DROP INDEX IF EXISTS ix_books_authors")
    op.execute("DROP INDEX IF EXISTS idx_book_embeddings_embedding_hnsw")
