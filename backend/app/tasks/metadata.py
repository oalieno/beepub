"""Celery tasks for fetching external metadata (Goodreads, Readmoo)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _process_metadata_job(book_id: str) -> None:
    """Fetch metadata from all sources for the given book_id."""
    from sqlalchemy import text

    from app.database import create_task_engine
    from app.services.metadata_sources import GoodreadsSource, ReadmooSource

    sources = [GoodreadsSource(), ReadmooSource()]

    async with create_task_engine() as (_engine, session_factory):
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
                logger.warning("Book %s not found, skipping", book_id)
                return

            display_title = row["title"] or row["epub_title"] or ""
            display_authors = row["authors"] or row["epub_authors"] or []
            isbn = row["epub_isbn"]

            if not display_title:
                logger.info("Book %s has no title, skipping metadata fetch", book_id)
                return

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
                            "Using pinned URL for %s book %s: %s",
                            source.source_name,
                            book_id,
                            pinned_url,
                        )
                        fetch_result = await source.fetch(pinned_url)
                        source_url = pinned_url
                    else:
                        results = await source.search(
                            display_title, display_authors, isbn
                        )
                        if not results:
                            logger.info(
                                "No results from %s for book %s",
                                source.source_name,
                                book_id,
                            )
                            continue

                        best = results[0]
                        fetch_result = await source.fetch(best.url)
                        source_url = fetch_result.source_url

                    # Upsert external_metadata
                    await db.execute(
                        text(
                            """
                            INSERT INTO external_metadata
                                (
                                    id,
                                    book_id,
                                    source,
                                    source_url,
                                    rating,
                                    rating_count,
                                    reviews,
                                    raw_data,
                                    fetched_at
                                )
                            VALUES
                                (
                                    gen_random_uuid(),
                                    :book_id,
                                    :source,
                                    :source_url,
                                    :rating,
                                    :rating_count,
                                    CAST(:reviews AS jsonb),
                                    CAST(:raw_data AS jsonb),
                                    :fetched_at
                                )
                            ON CONFLICT (book_id, source) DO UPDATE SET
                                source_url = EXCLUDED.source_url,
                                rating = EXCLUDED.rating,
                                rating_count = EXCLUDED.rating_count,
                                reviews = EXCLUDED.reviews,
                                raw_data = EXCLUDED.raw_data,
                                fetched_at = EXCLUDED.fetched_at
                        """
                        ),
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
                    logger.info(
                        "Updated %s metadata for book %s",
                        source.source_name,
                        book_id,
                    )
                except Exception as e:
                    logger.error(
                        "Error processing %s for book %s: %s",
                        source.source_name,
                        book_id,
                        e,
                    )
                    await db.rollback()


@celery.task(name="app.tasks.metadata.fetch_metadata", bind=True, max_retries=3)
def fetch_metadata(self, book_id: str) -> None:
    """Celery task: fetch external metadata for a book."""
    try:
        from app.celeryapp import run_async

        run_async(_process_metadata_job(book_id))
    except Exception as exc:
        logger.exception("fetch_metadata failed for book %s", book_id)
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
                        "Last scheduled %.1f days ago, interval is %d days, skipping",
                        days_since,
                        interval_days,
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
                logger.info("Queued %d books for metadata refresh", len(book_ids))

            # Record last scheduled time
            await client.set(LAST_SCHEDULED_KEY, datetime.now(UTC).isoformat())
        finally:
            await client.aclose()


@celery.task(name="app.tasks.metadata.check_and_schedule_refresh")
def check_and_schedule_refresh() -> None:
    """Celery beat task: periodic metadata refresh check."""
    from app.celeryapp import run_async

    run_async(_check_and_schedule_refresh())
