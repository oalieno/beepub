"""Trigram GIN indexes for book search columns

Every book search filter is a leading-wildcard ILIKE ('%q%') over seven
columns, which a btree index can't serve — each search was a full
sequential scan of books. pg_trgm GIN indexes make them indexable
(BitmapOr across the per-column indexes).

The two authors columns are varchar[] arrays; a raw CAST isn't IMMUTABLE
so it can't be indexed. beepub_join_authors() wraps array_to_string as
an IMMUTABLE function — the query side searches through the same
function so the expression indexes match. (Bonus: matching against
"a b" instead of the cast's "{a,b}" drops the brace/comma artifacts.)

Revision ID: 044
Revises: 043
"""

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None

PLAIN_COLUMNS = ["title", "epub_title", "series", "epub_series", "epub_isbn"]
ARRAY_COLUMNS = ["authors", "epub_authors"]


def upgrade() -> None:
    # Already created by migration 019, but harmless and keeps this
    # migration self-contained.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION beepub_join_authors(character varying[])
        RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE RETURNS NULL ON NULL INPUT
        AS $$ SELECT array_to_string($1, ' ') $$
        """
    )

    for col in PLAIN_COLUMNS:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_books_{col}_trgm "
            f"ON books USING gin ({col} gin_trgm_ops)"
        )
    for col in ARRAY_COLUMNS:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_books_{col}_trgm "
            f"ON books USING gin ((beepub_join_authors({col})) gin_trgm_ops)"
        )


def downgrade() -> None:
    for col in PLAIN_COLUMNS + ARRAY_COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS ix_books_{col}_trgm")
    op.execute("DROP FUNCTION IF EXISTS beepub_join_authors(character varying[])")
