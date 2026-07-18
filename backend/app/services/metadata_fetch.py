"""Shared helpers for metadata fetching (used by both per-book and backfill tasks).

This is the app-side seam between the plugin package (pure, no app.*
imports) and the database: plugin instantiation from operator settings,
and BookRecord <-> external_metadata row serialization."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from sqlalchemy import text

from app.config import settings as app_config
from app.plugins.metadata import BookQuery, BookRecord, registry

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
    *,
    job_only: bool = False,
) -> list[MetadataPlugin]:
    """Instantiate plugins with the operator settings. `job_only`
    additionally applies the background job's source-list setting;
    interactive surfaces see every enabled plugin."""
    from app.services.settings import get_all_settings

    async with session_factory() as settings_db:
        app_settings = await get_all_settings(settings_db)

    if job_only:
        return registry.job_plugins(app_settings)
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


# ---------------------------------------------------------------------------
# Resolve cache — framework infrastructure, like rate limiting: plugins
# know nothing about it. Keyed (source, most-precise clue), so the same
# question never hits an upstream twice within the TTL — an interactive
# lookup warms the cache and the background job right after gets free
# hits. Only FOUND records are cached: a not-found from a clue-poor
# query (isbn-only lookup) must not shadow a richer query (the job also
# has title/authors, and its empty markers are permanent). Errors raise
# and are never cached; any cache failure degrades to a live resolve.
# ---------------------------------------------------------------------------

RESOLVE_CACHE_TTL = 24 * 3600
_RESOLVE_CACHE_PREFIX = "beepub:resolve"


def _clue_fingerprint(query: BookQuery) -> str:
    """Most-precise-clue precedence, mirroring how plugins locate: a URL
    or ISBN identifies the same book regardless of which title/author
    clues ride along — so an isbn-only interactive lookup and the
    richer background-job query share cache entries."""
    if query.url:
        raw = f"url={query.url}"
    elif query.isbn:
        raw = f"isbn={query.isbn}"
    else:
        authors = ",".join(a.strip().lower() for a in query.authors)
        raw = f"title={(query.title or '').strip().lower()}|authors={authors}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def cached_resolve(plugin: MetadataPlugin, query: BookQuery) -> BookRecord | None:
    key = f"{_RESOLVE_CACHE_PREFIX}:{plugin.name}:{_clue_fingerprint(query)}"
    client = None
    try:
        try:
            client = aioredis.from_url(app_config.redis_url)
            payload = await client.get(key)
            if payload is not None:
                return BookRecord(**json.loads(payload))
        except Exception as e:
            logger.debug(f"resolve cache read failed: {e}")

        record = await plugin.resolve(query)

        if record is not None and client is not None:
            try:
                await client.set(
                    key,
                    json.dumps(dataclasses.asdict(record)),
                    ex=RESOLVE_CACHE_TTL,
                )
            except Exception as e:
                logger.debug(f"resolve cache write failed: {e}")
        return record
    finally:
        if client is not None:
            await client.aclose()


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
