"""Shared helpers for metadata fetching (used by both per-book and backfill tasks).

This is the app-side seam between the plugin package (pure, no app.*
imports) and the database: plugin instantiation from operator settings,
and BookRecord <-> external_metadata row serialization."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.plugins.metadata import BookRecord, registry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.plugins.metadata import MetadataPlugin

logger = logging.getLogger(__name__)

# BookRecord fields stored inside the `record` JSONB. The others are
# real columns: rating/rating_count/readers_count feed the popularity
# SQL, reviews and source_url feed the ratings UI.
RECORD_JSON_FIELDS = (
    "title",
    "authors",
    "publisher",
    "description",
    "published_date",
    "language",
    "cover_url",
    "tags",
)


def record_json(record: BookRecord) -> dict:
    return {name: getattr(record, name) for name in RECORD_JSON_FIELDS}


async def init_metadata_plugins(
    session_factory: async_sessionmaker,
) -> list[MetadataPlugin]:
    """Instantiate every enabled plugin with the operator settings."""
    from app.services.settings import get_all_settings

    async with session_factory() as settings_db:
        app_settings = await get_all_settings(settings_db)

    return registry.enabled_plugins(app_settings)


async def fetch_book_info(
    db: AsyncSession, book_id: str
) -> tuple[str, list[str], str | None] | None:
    """Return (title, authors, isbn) for a book, or None if not found / no title."""
    result = await db.execute(
        text(
            "SELECT id, epub_title, epub_authors, epub_isbn, title, authors "
            "FROM books WHERE id = :id"
        ),
        {"id": book_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        return None

    display_title = row["title"] or row["epub_title"] or ""
    display_authors = row["authors"] or row["epub_authors"] or []
    isbn = row["epub_isbn"]

    if not display_title:
        return None

    return display_title, display_authors, isbn


async def upsert_external_metadata(
    db: AsyncSession,
    book_id: str,
    source_name: str,
    record: BookRecord,
    source_url: str | None = None,
) -> None:
    """INSERT ... ON CONFLICT DO UPDATE for external_metadata.

    `source_url` overrides the record's own — the pinned-URL flow keeps
    the admin's manually-entered link."""
    await db.execute(
        text("""
            INSERT INTO external_metadata
                (id, book_id, source, source_url, rating, rating_count,
                 readers_count, reviews, record, fetched_at)
            VALUES
                (gen_random_uuid(), :book_id, :source, :source_url,
                 :rating, :rating_count, :readers_count,
                 CAST(:reviews AS jsonb), CAST(:record AS jsonb), :fetched_at)
            ON CONFLICT (book_id, source) DO UPDATE SET
                source_url = EXCLUDED.source_url,
                rating = EXCLUDED.rating,
                rating_count = EXCLUDED.rating_count,
                readers_count = EXCLUDED.readers_count,
                reviews = EXCLUDED.reviews,
                record = EXCLUDED.record,
                fetched_at = EXCLUDED.fetched_at
        """),
        {
            "book_id": book_id,
            "source": source_name,
            "source_url": source_url or record.source_url,
            "rating": record.rating,
            "rating_count": record.rating_count,
            "readers_count": record.readers_count,
            "reviews": json.dumps(record.reviews) if record.reviews else None,
            "record": json.dumps(record_json(record)),
            "fetched_at": datetime.now(UTC),
        },
    )
    await db.commit()


async def run_tag_mapping(session_factory: async_sessionmaker, book_id: str) -> None:
    """Run deterministic tag mapping for a book."""
    from app.services.tag_mapping import generate_tags_from_metadata

    try:
        async with session_factory() as db:
            count = await generate_tags_from_metadata(db, uuid.UUID(book_id))
            await db.commit()
            if count:
                logger.info(f"Mapped {count} external tags for book {book_id}")
    except Exception as e:
        logger.error(f"Error mapping tags for book {book_id}: {e}")
