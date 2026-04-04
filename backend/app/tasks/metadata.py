"""Celery tasks for fetching external metadata."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _process_metadata_job(book_id: str) -> None:
    """Fetch metadata from all sources for the given book_id."""
    from sqlalchemy import text

    from app.database import create_task_engine
    from app.services.metadata_fetch import (
        fetch_book_info,
        init_metadata_sources,
        run_tag_mapping,
        search_and_fetch,
        upsert_external_metadata,
    )
    from app.services.metadata_sources.base import RateLimitError

    async with create_task_engine() as (_engine, session_factory):
        sources = await init_metadata_sources(session_factory)

        async with session_factory() as db:
            book_info = await fetch_book_info(db, book_id)
            if not book_info:
                logger.warning(f"Book {book_id} not found or has no title, skipping")
                return

            display_title, display_authors, isbn = book_info

            for source in sources:
                try:
                    # Check for manually pinned URL
                    existing = await db.execute(
                        text(
                            "SELECT source_url FROM external_metadata "
                            "WHERE book_id = :book_id AND source = :source"
                        ),
                        {"book_id": book_id, "source": source.source_name},
                    )
                    existing_row = existing.mappings().one_or_none()
                    pinned_url = existing_row["source_url"] if existing_row else None

                    if pinned_url:
                        logger.info(
                            f"Using pinned URL for {source.source_name} book {book_id}: {pinned_url}"
                        )
                        fetch_result = await source.fetch(pinned_url)
                        source_url = pinned_url
                    else:
                        result = await search_and_fetch(
                            source, display_title, display_authors, isbn, book_id
                        )
                        if not result:
                            continue
                        fetch_result, source_url = result

                    await upsert_external_metadata(
                        db, book_id, source.source_name, source_url, fetch_result
                    )
                    logger.info(
                        f"Updated {source.source_name} metadata for book {book_id}"
                    )
                except RateLimitError:
                    logger.warning(
                        f"Rate limited by {source.source_name} for book {book_id}, skipping"
                    )
                except Exception as e:
                    logger.error(
                        f"Error processing {source.source_name} for book {book_id}: {e}"
                    )
                    await db.rollback()

            # After all sources fetched, run deterministic tag mapping
            await run_tag_mapping(session_factory, book_id)


@celery.task(name="app.tasks.metadata.fetch_metadata", bind=True, max_retries=3)
def fetch_metadata(self, book_id: str) -> None:
    """Celery task: fetch external metadata for a book."""
    try:
        from app.celeryapp import run_async

        run_async(_process_metadata_job(book_id))
    except Exception as exc:
        logger.exception(f"fetch_metadata failed for book {book_id}")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


async def _check_and_schedule_refresh() -> None:
    """Hourly check: read settings from DB and queue books if conditions are met."""
    import redis.asyncio as aioredis
    from sqlalchemy import text

    from app.config import settings
    from app.database import create_task_engine

    LAST_SCHEDULED_KEY = "beepub:metadata:last_scheduled"

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            # Read settings
            async def _get_setting(key: str, default: str = "") -> str:
                result = await db.execute(
                    text("SELECT value FROM app_settings WHERE key = :key"),
                    {"key": key},
                )
                row = result.one_or_none()
                return row[0] if row else default

            enabled = await _get_setting("metadata_refresh_enabled", "true")
            if enabled != "true":
                return

            tz_name = await _get_setting("timezone", "UTC")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("UTC")

            now_local = datetime.now(tz)
            refresh_hour = int(await _get_setting("metadata_refresh_hour", "3"))
            if now_local.hour != refresh_hour:
                return

            interval_days = int(
                await _get_setting("metadata_refresh_interval_days", "7")
            )
            cooldown_days = int(
                await _get_setting("metadata_refresh_cooldown_days", "30")
            )

        # Check if we already ran within the interval
        client = aioredis.from_url(settings.redis_url)
        try:
            last_run = await client.get(LAST_SCHEDULED_KEY)
            if last_run:
                last_run_dt = datetime.fromisoformat(last_run.decode())
                days_since = (datetime.now(UTC) - last_run_dt).total_seconds() / 86400
                if days_since < interval_days:
                    logger.debug(
                        f"Last scheduled {days_since:.1f} days ago, interval is {interval_days} days, skipping"
                    )
                    return

            # Query books that need refresh
            async with session_factory() as db:
                result = await db.execute(
                    text("""
                        SELECT b.id FROM books b
                        LEFT JOIN (
                            SELECT book_id, MAX(fetched_at) as last_fetched
                            FROM external_metadata GROUP BY book_id
                        ) em ON em.book_id = b.id
                        WHERE em.last_fetched IS NULL
                           OR em.last_fetched < NOW() - MAKE_INTERVAL(days => :cooldown)
                    """),
                    {"cooldown": cooldown_days},
                )
                book_ids = [str(row[0]) for row in result.fetchall()]

            if not book_ids:
                logger.info("No books need metadata refresh")
            else:
                from app.tasks.auto_tag import auto_tag_book

                for book_id in book_ids:
                    fetch_metadata.apply_async(
                        args=[book_id], link=auto_tag_book.si(book_id)
                    )
                logger.info(f"Queued {len(book_ids)} books for metadata refresh")

            # Record last scheduled time
            await client.set(LAST_SCHEDULED_KEY, datetime.now(UTC).isoformat())
        finally:
            await client.aclose()


@celery.task(name="app.tasks.metadata.check_and_schedule_refresh")
def check_and_schedule_refresh() -> None:
    """Celery beat task: periodic metadata refresh check."""
    from app.celeryapp import run_async

    run_async(_check_and_schedule_refresh())
