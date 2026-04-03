"""Metadata backfill task: fetch external metadata + deterministic tag mapping.

No AI/LLM calls. Handles rate limits with Redis cooldown flags.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy import text

from app.config import settings as app_config

logger = logging.getLogger(__name__)

# Delay between books to be polite to scraped sites (seconds)
DELAY_BETWEEN_BOOKS = 1.5

# Redis key prefix for rate limit cooldown
RATELIMIT_KEY_PREFIX = "beepub:ratelimit"

# Cooldown TTLs per source (seconds)
RATELIMIT_TTLS = {
    "google_books": 86400,  # 24h (daily quota of 1000)
    "hardcover": 60,  # 60s (per-minute limit of 60)
    "goodreads": 300,  # 5min
    "readmoo": 300,  # 5min
}


async def _is_rate_limited(redis_client: aioredis.Redis, source: str) -> bool:
    """Check if a source is currently rate-limited."""
    return await redis_client.exists(f"{RATELIMIT_KEY_PREFIX}:{source}") > 0


async def _set_rate_limited(redis_client: aioredis.Redis, source: str) -> None:
    """Mark a source as rate-limited with appropriate TTL."""
    ttl = RATELIMIT_TTLS.get(source, 300)
    await redis_client.set(f"{RATELIMIT_KEY_PREFIX}:{source}", "1", ex=ttl)
    logger.warning("Rate limited by %s — cooldown %ds", source, ttl)


async def _write_empty_marker(db, book_id: str, source_name: str) -> None:
    """Write an empty external_metadata row to mark 'searched but not found'."""
    await db.execute(
        text("""
            INSERT INTO external_metadata (id, book_id, source, fetched_at)
            VALUES (gen_random_uuid(), :book_id, :source, :fetched_at)
            ON CONFLICT (book_id, source) DO UPDATE SET fetched_at = EXCLUDED.fetched_at
        """),
        {
            "book_id": book_id,
            "source": source_name,
            "fetched_at": datetime.now(UTC),
        },
    )
    await db.commit()


async def _run_metadata_backfill(book_id: str) -> None:
    """Fetch metadata from all sources for a book, then run deterministic tag mapping.

    Unlike fetch_metadata, this does NOT chain to auto_tag_book (no AI).
    Skips already-fetched sources. Writes empty markers for not-found books.
    Respects rate limit cooldown flags in Redis.
    """
    from app.database import create_task_engine
    from app.services.metadata_sources import (
        GoodreadsSource,
        GoogleBooksSource,
        HardcoverSource,
        ReadmooSource,
    )
    from app.services.metadata_sources.base import RateLimitError
    from app.services.settings import get_all_settings as _get_settings
    from app.services.tag_mapping import generate_tags_from_metadata

    redis_client = aioredis.from_url(app_config.redis_url)

    try:
        async with create_task_engine() as (_engine, session_factory):
            # Load API keys
            async with session_factory() as settings_db:
                app_settings = await _get_settings(settings_db)

            google_api_key = app_settings.get("google_books_api_key", "")
            hardcover_token = app_settings.get("hardcover_api_token", "")

            sources = [
                GoodreadsSource(),
                ReadmooSource(),
                GoogleBooksSource(api_key=google_api_key),
                HardcoverSource(api_token=hardcover_token),
            ]

            async with session_factory() as db:
                result = await db.execute(
                    text(
                        "SELECT id, epub_title, epub_authors, epub_isbn, title, authors "
                        "FROM books WHERE id = :id"
                    ),
                    {"id": book_id},
                )
                row = result.mappings().one_or_none()
                if not row:
                    return

                display_title = row["title"] or row["epub_title"] or ""
                display_authors = row["authors"] or row["epub_authors"] or []
                isbn = row["epub_isbn"]

                if not display_title:
                    return

                for source in sources:
                    try:
                        # Skip if rate-limited
                        if await _is_rate_limited(redis_client, source.source_name):
                            continue

                        # Skip if already fetched this source
                        existing = await db.execute(
                            text(
                                "SELECT 1 FROM external_metadata "
                                "WHERE book_id = :book_id AND source = :source"
                            ),
                            {"book_id": book_id, "source": source.source_name},
                        )
                        if existing.one_or_none():
                            continue

                        # Search
                        results = await source.search(
                            display_title, display_authors, isbn
                        )
                        if not results:
                            await _write_empty_marker(db, book_id, source.source_name)
                            continue

                        best = results[0]
                        if best.score < 60:
                            await _write_empty_marker(db, book_id, source.source_name)
                            continue

                        if best.prefetched:
                            fetch_result = best.prefetched
                        else:
                            fetch_result = await source.fetch(best.url)
                        source_url = fetch_result.source_url

                        # Upsert external_metadata
                        await db.execute(
                            text("""
                                INSERT INTO external_metadata
                                    (id, book_id, source, source_url, rating,
                                     rating_count, reviews, raw_data, fetched_at)
                                VALUES
                                    (gen_random_uuid(), :book_id, :source, :source_url,
                                     :rating, :rating_count, CAST(:reviews AS jsonb),
                                     CAST(:raw_data AS jsonb), :fetched_at)
                                ON CONFLICT (book_id, source) DO UPDATE SET
                                    source_url = EXCLUDED.source_url,
                                    rating = EXCLUDED.rating,
                                    rating_count = EXCLUDED.rating_count,
                                    reviews = EXCLUDED.reviews,
                                    raw_data = EXCLUDED.raw_data,
                                    fetched_at = EXCLUDED.fetched_at
                            """),
                            {
                                "book_id": book_id,
                                "source": source.source_name,
                                "source_url": source_url,
                                "rating": fetch_result.rating,
                                "rating_count": fetch_result.rating_count,
                                "reviews": json.dumps(fetch_result.reviews)
                                if fetch_result.reviews
                                else None,
                                "raw_data": json.dumps(fetch_result.raw_data)
                                if fetch_result.raw_data
                                else None,
                                "fetched_at": datetime.now(UTC),
                            },
                        )
                        await db.commit()
                    except RateLimitError:
                        await _set_rate_limited(redis_client, source.source_name)
                        await db.rollback()
                    except Exception as e:
                        logger.error(
                            "Error fetching %s for book %s: %s",
                            source.source_name,
                            book_id,
                            e,
                        )
                        await db.rollback()

            # Run deterministic tag mapping (no AI)
            try:
                async with session_factory() as db:
                    count = await generate_tags_from_metadata(db, uuid.UUID(book_id))
                    await db.commit()
                    if count:
                        logger.info(
                            "Backfill: mapped %d tags for book %s", count, book_id
                        )
            except Exception as e:
                logger.error("Error mapping tags for book %s: %s", book_id, e)

            # Rate limit: pause between books
            await asyncio.sleep(DELAY_BETWEEN_BOOKS)
    finally:
        await redis_client.aclose()
