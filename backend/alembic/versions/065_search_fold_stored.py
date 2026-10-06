"""Search reads the folded text from stored columns

Since 064 beepub_norm() carries a 4,221-character Traditional→
Simplified map, and translate() walks that map for every character it
is given: folding one title costs about 0.3 ms, where the 056 version
cost microseconds. The search compared beepub_norm(column) against the
folded query, which was only ever cheap while an expression index
answered it — and a trigram index cannot answer a pattern shorter than
three characters. A two-character query (the usual length of a Chinese
word) therefore folded every search field of every book, three times
per request: about 30 s on a 64k-book library.

The folded text is now stored: beepub_norm() runs when a book is
written, never while searching.

- eight generated columns, one per search field, replace the 056/058
  expression indexes (same index names, now on the columns). The fuzzy
  tier and the relevance sort read these.
- search_norm joins the eight with newlines: the substring tiers read
  one column instead of OR-ing seventeen conditions, so even the scan
  a short pattern forces is a single LIKE per book. A folded string has
  no whitespace, so a pattern cannot match across two fields.

Changing beepub_norm() later: PostgreSQL 16 cannot recompute a
generated column in place, so a migration that redefines the function
must drop and re-add these columns (and their indexes) — a REINDEX is
no longer enough.

On upgrade the table is rewritten once under an exclusive lock, each
book folded twice (its own columns, then search_norm): about 1.5 min
per 64k books. The old expression indexes are dropped first so the
rewrite does not rebuild them.

Revision ID: 065
Revises: 064
"""

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None

# column → the 056/058 index expression it stores
FOLDED = {
    "title_norm": "beepub_norm(title)",
    "epub_title_norm": "beepub_norm(epub_title)",
    "authors_norm": "beepub_norm(beepub_join_authors(authors))",
    "epub_authors_norm": "beepub_norm(beepub_join_authors(epub_authors))",
    "series_norm": "beepub_norm(series)",
    "epub_series_norm": "beepub_norm(epub_series)",
    "tags_norm": "beepub_norm(beepub_join_authors(tags))",
    "epub_tags_norm": "beepub_norm(beepub_join_authors(epub_tags))",
}

# A generated column cannot read another generated column, so the fold
# is spelled out again.
SEARCH_NORM = " || E'\\n' || ".join(f"coalesce({expr}, '')" for expr in FOLDED.values())


def _index(column: str) -> str:
    return f"ix_books_{column}_trgm"


def upgrade() -> None:
    for column in FOLDED:
        op.execute(f"DROP INDEX IF EXISTS {_index(column)}")

    columns = {**FOLDED, "search_norm": SEARCH_NORM}
    op.execute(
        "ALTER TABLE books "
        + ", ".join(
            f"ADD COLUMN {column} text GENERATED ALWAYS AS ({expr}) STORED"
            for column, expr in columns.items()
        )
    )
    for column in columns:
        op.execute(
            f"CREATE INDEX {_index(column)} ON books USING gin ({column} gin_trgm_ops)"
        )
    op.execute("ANALYZE books")


def downgrade() -> None:
    # Dropping a column drops its index and rewrites nothing; the
    # expression indexes fold every book again as they are rebuilt.
    op.execute(
        "ALTER TABLE books "
        + ", ".join(f"DROP COLUMN {column}" for column in [*FOLDED, "search_norm"])
    )
    for column, expr in FOLDED.items():
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {_index(column)} "
            f"ON books USING gin (({expr}) gin_trgm_ops)"
        )
