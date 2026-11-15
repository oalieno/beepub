"""A series's key is one stored column

A series is identified by its name, trimmed and lower-cased, within a
library. That key was computed wherever it was needed — some sixteen
places, in three spellings — and they did not agree: Python's
``str.strip()`` removes a full-width space (U+3000), PostgreSQL's
``btrim()`` removes only the ASCII one. A Chinese series whose name was
stored with a full-width space at either end therefore had one key in
the tables that remember things about a series (ratings, notes, shelf
membership — written from Python) and another in every query that looks
its books up, and the two never met.

``books.series_key`` is now a stored generated column, trimmed of every
character Python calls whitespace, so there is one definition and the
keys already stored keep matching. It is indexed: "the other books of
this series" was a scan of the table.

On upgrade the books table is rewritten once under an exclusive lock
(as in 065): about a minute or two per 64k books.

Revision ID: 068
Revises: 067
"""

from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None

# Every character for which Python's str.isspace() is true: what
# str.strip() removes, and so what the keys stored before this migration
# were trimmed of.
_WHITESPACE = (
    [0x20]
    + list(range(0x09, 0x0E))
    + list(range(0x1C, 0x20))
    + [0x85, 0xA0, 0x1680]
    + list(range(0x2000, 0x200B))
    + [0x2028, 0x2029, 0x202F, 0x205F, 0x3000]
)
# (Spelled as an escaped literal — U&'\\0020\\0009…' — so the definition
# reads the same in every client and dump.)
WHITESPACE_SQL = "U&'" + "".join(f"\\{c:04X}" for c in _WHITESPACE) + "'"

SERIES_KEY = (
    f"nullif(lower(btrim(coalesce(series, epub_series), {WHITESPACE_SQL})), '')"
)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE books ADD COLUMN series_key text "
        f"GENERATED ALWAYS AS ({SERIES_KEY}) STORED"
    )
    op.execute(
        "CREATE INDEX ix_books_series_key ON books (series_key) "
        "WHERE series_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_books_series_key")
    op.execute("ALTER TABLE books DROP COLUMN series_key")
