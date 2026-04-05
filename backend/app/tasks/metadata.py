"""Metadata task utilities — auto-start backfill and single-source fetch."""

from __future__ import annotations

import logging

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _auto_start_backfill() -> None:
    """Start a metadata_backfill run if none is currently pending."""
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


@celery.task(name="app.tasks.metadata.fetch_single_source", bind=True, max_retries=2)
def fetch_single_source(self, book_id: str, source_name: str) -> None:
    """Celery task: fetch one specific source for a book using its stored URL."""
    try:
        from app.celeryapp import run_async

        run_async(_fetch_single_source(book_id, source_name))
    except Exception as exc:
        logger.exception(
            f"fetch_single_source failed for book {book_id} source {source_name}"
        )
        raise self.retry(exc=exc, countdown=30)


async def _fetch_single_source(book_id: str, source_name: str) -> None:
    """Fetch a single source using its stored source_url, then re-map tags."""
    from sqlalchemy import text

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
