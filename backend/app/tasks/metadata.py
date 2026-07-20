"""Metadata tasks: per-book backfill, single-source fetch, and bulk auto-start.

The core function _run_fetch_book_metadata() is shared by both:
- fetch_book_metadata (per-book celery task, default queue)
- bulk_jobs._execute_book_task (bulk orchestrator, bulk queue)

No AI/LLM calls. Handles rate limits with Redis cooldown flags — the
cooldown length is each plugin's declared ratelimit_cooldown; plugins
themselves never touch Redis or sleep.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy import text

from app.celeryapp import celery
from app.config import settings as app_config
from app.plugins.metadata import BookQuery, Clue, RateLimitError, registry

logger = logging.getLogger(__name__)

# Delay between books to be polite to scraped sites (seconds)
DELAY_BETWEEN_BOOKS = 1.5

# Redis key prefix for rate limit cooldown
RATELIMIT_KEY_PREFIX = "beepub:ratelimit"


# ---------------------------------------------------------------------------
# Rate limit helpers
# ---------------------------------------------------------------------------


async def _is_rate_limited(redis_client: aioredis.Redis, source: str) -> bool:
    """Check if a source is currently rate-limited."""
    return await redis_client.exists(f"{RATELIMIT_KEY_PREFIX}:{source}") > 0


async def _set_rate_limited(redis_client: aioredis.Redis, source: str) -> None:
    """Mark a source as rate-limited with its declared cooldown TTL."""
    plugin_cls = registry.get_plugin_class(source)
    ttl = plugin_cls.ratelimit_cooldown if plugin_cls else 300
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
    """Resolve every enabled plugin for a book, then run deterministic
    tag mapping.

    Skips already-fetched sources. Writes empty markers for not-found
    books (and for plugins that can't locate this book at all, so
    metadata_count still completes). Respects rate limit cooldown flags
    in Redis. A plugin raising ≠ not found: no marker, retried next run.
    """
    import uuid as _uuid

    from app.database import create_task_engine
    from app.services.metadata_fetch import (
        cached_resolve,
        fetch_book_info,
        init_metadata_plugins,
        run_tag_mapping,
        upsert_external_metadata,
    )
    from app.services.popularity import recompute_popularity

    redis_client = aioredis.from_url(app_config.redis_url)

    # Per-book lock: with acks_late a worker crash redelivers the task, and
    # the same book can be dispatched via both the bulk queue and the
    # default-queue task — without this both re-scrape every source.
    lock = redis_client.lock(f"beepub:metadata:{book_id}", timeout=900)
    if not await lock.acquire(blocking=False):
        logger.info(f"Metadata backfill already running for book {book_id}, skipping")
        await redis_client.aclose()
        return

    try:
        async with create_task_engine() as (_engine, session_factory):
            plugins = await init_metadata_plugins(session_factory, job_only=True)

            async with session_factory() as db:
                book_info = await fetch_book_info(db, book_id)
            if not book_info:
                return

            display_title, display_authors, isbn = book_info
            available_clues = {Clue.TITLE} | ({Clue.ISBN} if isbn else set())

            for plugin in plugins:
                try:
                    # Skip if rate-limited
                    if await _is_rate_limited(redis_client, plugin.name):
                        continue

                    # Skip if already fetched this source
                    async with session_factory() as db:
                        existing = await db.execute(
                            text(
                                "SELECT 1 FROM external_metadata "
                                "WHERE book_id = :book_id AND source = :source"
                            ),
                            {"book_id": book_id, "source": plugin.name},
                        )
                        already_fetched = existing.one_or_none() is not None
                    if already_fetched:
                        continue

                    if not (plugin.accepts & available_clues):
                        # This plugin can never locate this book (e.g. an
                        # ISBN-only source, a book without an ISBN) —
                        # record it like a not-found so the book's
                        # metadata_count still reaches the full set.
                        async with session_factory() as db:
                            await _write_empty_marker(db, book_id, plugin.name)
                        continue

                    # HTTP scraping runs with NO session open — the task
                    # engine pool is tiny and these calls take seconds each.
                    # cached_resolve: an interactive lookup moments earlier
                    # (the add-physical prefill) already warmed the cache.
                    record = await cached_resolve(
                        plugin,
                        BookQuery(
                            title=display_title,
                            authors=display_authors,
                            isbn=isbn,
                        ),
                    )

                    async with session_factory() as db:
                        if record is None:
                            await _write_empty_marker(db, book_id, plugin.name)
                        else:
                            await upsert_external_metadata(
                                db, book_id, plugin.name, record
                            )
                except RateLimitError:
                    await _set_rate_limited(redis_client, plugin.name)
                except Exception as e:
                    logger.error(
                        f"Error fetching {plugin.name} for book {book_id}: {e}"
                    )

            # Update metadata_count flag on the book
            async with session_factory() as db:
                count_result = await db.execute(
                    text(
                        "SELECT COUNT(DISTINCT source) FROM external_metadata "
                        "WHERE book_id = :book_id"
                    ),
                    {"book_id": book_id},
                )
                count = count_result.scalar() or 0
                await db.execute(
                    text("UPDATE books SET metadata_count = :count WHERE id = :id"),
                    {"count": count, "id": book_id},
                )
                await recompute_popularity(db, [_uuid.UUID(book_id)])
                await db.commit()

            # Run deterministic tag mapping (no AI)
            await run_tag_mapping(session_factory, book_id)

            # Rate limit: pause between books
            await asyncio.sleep(DELAY_BETWEEN_BOOKS)
    finally:
        try:
            await lock.release()
        except Exception:
            pass
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
    """Fetch a single source using its stored source_url, then re-map tags.

    The pinned URL rides in as the `url` clue — the most precise clue a
    plugin can get. The book's own clues ride along with it: google
    rebuilds its search stash from them (the search/detail merge that
    keeps TW descriptions), and a url-only query would archive a
    degraded record over a good one."""
    import uuid as _uuid

    from app.database import create_task_engine
    from app.services.metadata_fetch import (
        fetch_book_info,
        init_metadata_plugins,
        run_tag_mapping,
        upsert_external_metadata,
    )
    from app.services.popularity import recompute_popularity

    async with create_task_engine() as (_engine, session_factory):
        plugins = await init_metadata_plugins(session_factory)
        plugin = next((p for p in plugins if p.name == source_name), None)
        if not plugin:
            logger.warning(f"Unknown or disabled source: {source_name}")
            return

        async with session_factory() as db:
            book_info = await fetch_book_info(db, book_id)
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
            title, authors, isbn = book_info if book_info else ("", [], None)
            try:
                record = await plugin.resolve(
                    BookQuery(
                        url=pinned_url,
                        title=title or None,
                        authors=authors,
                        isbn=isbn,
                    )
                )
                if record is None:
                    logger.warning(
                        f"{source_name} returned nothing for pinned URL "
                        f"{pinned_url} (book {book_id})"
                    )
                    return
                await upsert_external_metadata(
                    db, book_id, source_name, record, source_url=pinned_url
                )
                await recompute_popularity(db, [_uuid.UUID(book_id)])
                await db.commit()
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
