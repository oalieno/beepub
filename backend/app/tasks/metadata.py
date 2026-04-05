"""Celery tasks for fetching external metadata."""

from __future__ import annotations

import logging

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
                    # Skip if already fetched (has row — found or not found)
                    existing = await db.execute(
                        text(
                            "SELECT 1 FROM external_metadata "
                            "WHERE book_id = :book_id AND source = :source"
                        ),
                        {"book_id": book_id, "source": source.source_name},
                    )
                    if existing.one_or_none():
                        continue

                    # Search and fetch
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
    """Celery task: fetch external metadata for a book (unfetched sources only)."""
    try:
        from app.celeryapp import run_async

        run_async(_process_metadata_job(book_id))
    except Exception as exc:
        logger.exception(f"fetch_metadata failed for book {book_id}")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@celery.task(name="app.tasks.metadata.fetch_single_source", bind=True, max_retries=2)
def fetch_single_source(self, book_id: str, source_name: str) -> None:
    """Celery task: fetch one specific source for a book using its pinned URL."""
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
            # Get the pinned URL
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
                logger.info(f"Fetched {source_name} for book {book_id} from pinned URL")
            except RateLimitError:
                logger.warning(f"Rate limited by {source_name}")
            except Exception as e:
                logger.error(f"Error fetching {source_name} for book {book_id}: {e}")
                await db.rollback()

        await run_tag_mapping(session_factory, book_id)
