"""Celery task for computing word counts from EPUB files."""

from __future__ import annotations

import logging
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.wordcount.compute_word_count", bind=True, max_retries=2)
def compute_word_count(self, book_id: str) -> None:
    """Compute word count for a single book and persist to DB."""
    import asyncio

    async def _run():
        from sqlalchemy import select, update

        from app.database import create_task_engine
        from app.models.book import Book
        from app.services.epub_text import count_words

        async with create_task_engine() as (_engine, session_factory):
            async with session_factory() as db:
                result = await db.execute(
                    select(Book.file_path).where(Book.id == uuid.UUID(book_id))
                )
                row = result.one_or_none()
                if not row:
                    logger.warning("Book %s not found, skipping word count", book_id)
                    return

                file_path = row[0]
                wc = await asyncio.to_thread(count_words, file_path)
                if wc is None:
                    logger.warning("Failed to count words for book %s", book_id)
                    return

                await db.execute(
                    update(Book)
                    .where(Book.id == uuid.UUID(book_id))
                    .values(word_count=wc)
                )
                await db.commit()
                logger.info("Book %s word count: %d", book_id, wc)

    try:
        from app.celeryapp import run_async

        run_async(_run())
    except Exception as exc:
        logger.exception("compute_word_count failed for book %s", book_id)
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
