"""Metadata plugin store

external_metadata becomes the per-source BookRecord store for the
metadata plugin system:

- ``source`` drops the DB enum (plain varchar now) so new plugins are
  drop-in — no ALTER TYPE per source
- ``record`` (JSONB) holds the structured raw fields a plugin parsed
  (title/authors/publisher/description/published_date/language/
  cover_url/tags); rating/rating_count/readers_count/reviews/source_url
  stay real columns (SQL consumers: popularity, the ratings UI).
  record NULL keeps meaning "searched, not found"
- ``readers_count`` is promoted from raw_data->>'users_read_count'
  (the popularity SQL reads it)
- legacy ``raw_data`` is converted into ``record`` — the old per-source
  tag-extraction knowledge is frozen below — and dropped

Revision ID: 054
Revises: 053
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None

_LEGACY_ENUM_SOURCES = ("goodreads", "readmoo", "google_books", "hardcover")


def _record_from_raw(source: str, raw: dict) -> dict:
    """Frozen copy of the per-source raw_data knowledge (previously
    tag_mapping.collect_raw_tags_from_metadata plus the google/hardcover
    field extraction) — turns a legacy raw_data dict into the BookRecord
    JSON shape."""
    record: dict = {
        "title": None,
        "authors": [],
        "publisher": None,
        "description": None,
        "published_date": None,
        "language": None,
        "cover_url": None,
        "tags": [],
    }
    tags: list[str] = []

    if source == "goodreads":
        tags = list(raw.get("genres") or []) + list(raw.get("shelves") or [])
    elif source == "readmoo":
        tags = list(raw.get("categories") or [])
    elif source == "google_books":
        # Hierarchical strings like "Fiction / Science Fiction" — keep
        # the full string plus each level.
        for cat in raw.get("categories") or []:
            tags.append(cat)
            for part in cat.split(" / "):
                part = part.strip()
                if part:
                    tags.append(part)
        if raw.get("mainCategory"):
            tags.append(raw["mainCategory"])
        record["description"] = raw.get("description")
        record["published_date"] = raw.get("publishedDate")
        record["language"] = raw.get("language")
    elif source == "hardcover":
        tags = (
            list(raw.get("genres") or [])
            + list(raw.get("moods") or [])
            + list(raw.get("tags") or [])
        )
        record["description"] = raw.get("description")
        record["published_date"] = raw.get("release_date")

    record["tags"] = tags
    return record


def upgrade() -> None:
    op.execute(
        "ALTER TABLE external_metadata "
        "ALTER COLUMN source TYPE varchar(50) USING source::text"
    )
    op.execute("DROP TYPE IF EXISTS metadatasource")

    op.add_column(
        "external_metadata",
        sa.Column("record", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "external_metadata",
        sa.Column("readers_count", sa.Integer(), nullable=True),
    )

    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, source, source_url, rating, raw_data FROM external_metadata"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        fetched = (
            row["source_url"] is not None
            or row["rating"] is not None
            or row["raw_data"] is not None
        )
        if not fetched:
            # Empty "searched, not found" marker: record stays NULL.
            continue
        raw = row["raw_data"] or {}
        readers = raw.get("users_read_count")
        bind.execute(
            sa.text(
                "UPDATE external_metadata "
                "SET record = CAST(:record AS jsonb), readers_count = :readers "
                "WHERE id = :id"
            ),
            {
                "record": json.dumps(_record_from_raw(row["source"], raw)),
                "readers": int(readers) if readers else None,
                "id": row["id"],
            },
        )

    op.drop_column("external_metadata", "raw_data")


def downgrade() -> None:
    op.add_column(
        "external_metadata",
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
    )

    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, source, record, readers_count FROM external_metadata "
                "WHERE record IS NOT NULL"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        rec = row["record"] or {}
        tags = rec.get("tags") or []
        if row["source"] == "goodreads":
            raw: dict = {"genres": tags, "shelves": []}
        elif row["source"] == "readmoo":
            raw = {"categories": tags}
        elif row["source"] == "google_books":
            raw = {
                "categories": tags,
                "description": rec.get("description"),
                "publishedDate": rec.get("published_date"),
                "language": rec.get("language"),
            }
        elif row["source"] == "hardcover":
            raw = {
                "tags": tags,
                "description": rec.get("description"),
                "release_date": rec.get("published_date"),
                "users_read_count": row["readers_count"],
            }
        else:
            raw = {"tags": tags}
        bind.execute(
            sa.text(
                "UPDATE external_metadata SET raw_data = CAST(:raw AS jsonb) "
                "WHERE id = :id"
            ),
            {"raw": json.dumps(raw), "id": row["id"]},
        )

    op.drop_column("external_metadata", "readers_count")
    op.drop_column("external_metadata", "record")

    # Rows from sources outside the legacy enum can't survive the cast.
    sources = ", ".join(f"'{s}'" for s in _LEGACY_ENUM_SOURCES)
    op.execute(f"DELETE FROM external_metadata WHERE source NOT IN ({sources})")
    op.execute(
        "CREATE TYPE metadatasource AS ENUM "
        f"({', '.join(repr(s) for s in _LEGACY_ENUM_SOURCES)})"
    )
    op.execute(
        "ALTER TABLE external_metadata "
        "ALTER COLUMN source TYPE metadatasource USING source::metadatasource"
    )
