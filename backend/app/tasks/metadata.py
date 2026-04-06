"""Metadata tasks: per-book backfill, single-source fetch, and bulk auto-start.

The core function _run_fetch_book_metadata() is shared by both:
- fetch_book_metadata (per-book celery task, default queue)
- bulk_jobs._execute_book_task (bulk orchestrator, bulk queue)

No AI/LLM calls. Handles rate limits with Redis cooldown flags.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy import text

from app.celeryapp import celery
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


# ---------------------------------------------------------------------------
# Rate limit helpers
# ---------------------------------------------------------------------------


async def _is_rate_limited(redis_client: aioredis.Redis, source: str) -> bool:
    """Check if a source is currently rate-limited."""
    return await redis_client.exists(f"{RATELIMIT_KEY_PREFIX}:{source}") > 0


async def _set_rate_limited(redis_client: aioredis.Redis, source: str) -> None:
    """Mark a source as rate-limited with appropriate TTL."""
    ttl = RATELIMIT_TTLS.get(source, 300)
    await redis_client.set(f"{RATELIMIT_KEY_PREFIX}:{source}", "1", ex=ttl)
    logger.warning(f"Rate limited by {source} — cooldown {ttl}s")


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


# ---------------------------------------------------------------------------
# Core: per-book metadata backfill (shared by small task + bulk task)
# ---------------------------------------------------------------------------


async def _run_fetch_book_metadata(book_id: str) -> None:
    """Fetch metadata from all sources for a book, then run deterministic tag mapping.

    Skips already-fetched sources. Writes empty markers for not-found books.
    Respects rate limit cooldown flags in Redis.
    """
    from app.database import create_task_engine
    from app.services.metadata_fetch import (
        fetch_book_info,
        init_metadata_sources,
        run_tag_mapping,
        search_and_fetch,
        upsert_external_metadata,
    )
    from app.services.metadata_sources.base import RateLimitError

    redis_client = aioredis.from_url(app_config.redis_url)

    try:
        async with create_task_engine() as (_engine, session_factory):
            sources = await init_metadata_sources(session_factory)

            async with session_factory() as db:
                book_info = await fetch_book_info(db, book_id)
                if not book_info:
                    return

                display_title, display_authors, isbn = book_info

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

                        result = await search_and_fetch(
                            source, display_title, display_authors, isbn, book_id
                        )
                        if not result:
                            await _write_empty_marker(db, book_id, source.source_name)
                            continue

                        fetch_result, source_url = result
                        await upsert_external_metadata(
                            db, book_id, source.source_name, source_url, fetch_result
                        )
                    except RateLimitError:
                        await _set_rate_limited(redis_client, source.source_name)
                        await db.rollback()
                    except Exception as e:
                        logger.error(
                            f"Error fetching {source.source_name} for book {book_id}: {e}"
                        )
                        await db.rollback()

            # Run deterministic tag mapping (no AI)
            await run_tag_mapping(session_factory, book_id)

            # Rate limit: pause between books
            await asyncio.sleep(DELAY_BETWEEN_BOOKS)
    finally:
        await redis_client.aclose()


@celery.task(name="app.tasks.metadata.fetch_book_metadata", bind=True, max_retries=2)
def fetch_book_metadata(self, book_id: str) -> None:
    """Celery task: run metadata backfill for a single book (default queue)."""
    try:
        from app.celeryapp import run_async

        run_async(_run_fetch_book_metadata(book_id))
    except Exception as exc:
        logger.exception(f"fetch_book_metadata failed for book {book_id}")
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Single-source fetch (manual refresh of one pinned source)
# ---------------------------------------------------------------------------


async def _run_fetch_metadata_source(book_id: str, source_name: str) -> None:
    """Fetch a single source using its stored source_url, then re-map tags."""
    from app.database import create_task_engine
    from app.services.metadata_fetch import (
        init_metadata_sources,
        run_tag_mapping,
        upsert_external_metadata,
    )
    from app.services.metadata_sources.base import RateLimitError

    async with create_task_engine() as (_engine, session_factory):
        sources = await init_metadata_sources(session_factory)
        source = next((s for s in sources if s.source_name == source_name), None)
        if not source:
            logger.warning(f"Unknown source: {source_name}")
            return

        async with session_factory() as db:
            result = await db.execute(
                text(
                    "SELECT source_url FROM external_metadata "
                    "WHERE book_id = :book_id AND source = :source"
                ),
                {"book_id": book_id, "source": source_name},
            )
            row = result.mappings().one_or_none()
            if not row or not row["source_url"]:
                logger.warning(f"No pinned URL for {source_name} book {book_id}")
                return

            pinned_url = row["source_url"]
            try:
                fetch_result = await source.fetch(pinned_url)
                await upsert_external_metadata(
                    db, book_id, source_name, pinned_url, fetch_result
                )
                logger.info(f"Fetched {source_name} for book {book_id} from URL")
            except RateLimitError:
                logger.warning(f"Rate limited by {source_name}")
            except Exception as e:
                logger.error(f"Error fetching {source_name} for book {book_id}: {e}")
                await db.rollback()

        await run_tag_mapping(session_factory, book_id)


@celery.task(name="app.tasks.metadata.fetch_metadata_source", bind=True, max_retries=2)
def fetch_metadata_source(self, book_id: str, source_name: str) -> None:
    """Celery task: fetch one specific source for a book using its stored URL."""
    try:
        from app.celeryapp import run_async

        run_async(_run_fetch_metadata_source(book_id, source_name))
    except Exception as exc:
        logger.exception(
            f"fetch_metadata_source failed for book {book_id} source {source_name}"
        )
        raise self.retry(exc=exc, countdown=30)


# ---------------------------------------------------------------------------
# Bulk auto-start (used by calibre sync)
# ---------------------------------------------------------------------------


async def _auto_start_backfill() -> None:
    """Start a metadata_backfill bulk run if none is currently pending."""
    from app.services.job_queue import get_pending_count, start_job

    pending = await get_pending_count("metadata_backfill")
    if pending > 0:
        logger.debug("Metadata backfill already pending (%d tasks), skipping", pending)
        return

    generation = await start_job("metadata_backfill")
    from app.tasks.bulk_jobs import run_bulk_job

    run_bulk_job.delay("metadata_backfill", generation)
    logger.info("Auto-started metadata backfill (generation %d)", generation)


def auto_start_backfill() -> None:
    """Sync wrapper for auto-starting backfill. Safe to call from sync code."""
    from app.celeryapp import run_async

    run_async(_auto_start_backfill())
