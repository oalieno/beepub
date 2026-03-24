"""Celery task for extracting text from EPUB files into DB chunks."""

from __future__ import annotations

import logging
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.tasks.text_extract.extract_book_text",
    bind=True,
    max_retries=2,
)
def extract_book_text(self, book_id: str) -> None:
    """Extract text from an EPUB and store as BookTextChunk rows."""
    import asyncio

    async def _run() -> None:
        from sqlalchemy import select

        from app.database import create_task_engine
        from app.models.book import Book
        from app.models.book_text import BookTextChunk
        from app.services.epub_text import extract_full_text

        async with create_task_engine() as (_engine, session_factory):
            async with session_factory() as db:
                bid = uuid.UUID(book_id)

                # Check if already extracted
                existing = await db.execute(
                    select(BookTextChunk.id)
                    .where(BookTextChunk.book_id == bid)
                    .limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    logger.info("Book %s already has text chunks, skipping", book_id)
                    return

                # Get book file path
                result = await db.execute(select(Book.file_path).where(Book.id == bid))
                row = result.one_or_none()
                if not row:
                    logger.warning(
                        "Book %s not found, skipping text extraction", book_id
                    )
                    return

                file_path = row[0]
                chunks = await asyncio.to_thread(
                    extract_full_text, file_path, max_chars=10_000_000
                )

                if not chunks:
                    logger.warning("No text extracted from book %s", book_id)
                    return

                for chunk in chunks:
                    db.add(
                        BookTextChunk(
                            book_id=bid,
                            spine_index=chunk.spine_index,
                            section_title=chunk.section_title,
                            text=chunk.text,
                            char_offset=chunk.char_offset,
                        )
                    )

                await db.commit()
                logger.info(
                    "Extracted %d text chunks from book %s", len(chunks), book_id
                )

    try:
        from app.celeryapp import run_async

        run_async(_run())
    except Exception as exc:
        logger.exception("extract_book_text failed for book %s", book_id)
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
