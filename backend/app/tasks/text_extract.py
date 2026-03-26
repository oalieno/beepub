"""Celery task for extracting text from EPUB files into DB chunks."""

from __future__ import annotations

import logging
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)

_IMAGE_BOOK_THRESHOLD = 500


async def _run_text_extract(book_id: str) -> None:
    """Extract text from an EPUB and store as BookTextChunk rows.

    Also computes word_count and sets is_image_book = (word_count < 500).
    If chunks already exist but word_count is NULL, classifies from stored chunks
    without re-opening the EPUB.
    """
    import asyncio

    from sqlalchemy import select, update

    from app.database import create_task_engine
    from app.models.book import Book
    from app.models.book_text import BookTextChunk
    from app.services.epub_text import (
        count_words_from_chunks,
        count_words_from_texts,
        extract_full_text,
    )

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            bid = uuid.UUID(book_id)

            # Check if already extracted
            existing = await db.execute(
                select(BookTextChunk.id).where(BookTextChunk.book_id == bid).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                # Chunks exist — check if classification is needed
                book_row = await db.execute(
                    select(Book.word_count).where(Book.id == bid)
                )
                current_wc = book_row.scalar_one_or_none()
                if current_wc is not None:
                    # Already classified, nothing to do
                    return

                # word_count is NULL — classify from stored DB chunks
                chunk_texts_result = await db.execute(
                    select(BookTextChunk.text).where(BookTextChunk.book_id == bid)
                )
                texts = [row[0] for row in chunk_texts_result.all()]
                wc = count_words_from_texts(texts)
                is_image = wc < _IMAGE_BOOK_THRESHOLD

                await db.execute(
                    update(Book)
                    .where(Book.id == bid)
                    .values(word_count=wc, is_image_book=is_image)
                )
                await db.commit()
                logger.info(
                    "Classified book %s: word_count=%d, is_image_book=%s",
                    book_id,
                    wc,
                    is_image,
                )
                return

            # Fresh extraction path
            result = await db.execute(select(Book.file_path).where(Book.id == bid))
            row = result.one_or_none()
            if not row:
                logger.warning("Book %s not found, skipping text extraction", book_id)
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

            # Compute word count from extracted chunks and classify
            wc = count_words_from_chunks(chunks)
            is_image = wc < _IMAGE_BOOK_THRESHOLD

            await db.execute(
                update(Book)
                .where(Book.id == bid)
                .values(word_count=wc, is_image_book=is_image)
            )

            await db.commit()
            logger.info(
                "Extracted %d text chunks from book %s (word_count=%d, is_image_book=%s)",
                len(chunks),
                book_id,
                wc,
                is_image,
            )


@celery.task(
    name="app.tasks.text_extract.extract_book_text",
    bind=True,
    max_retries=2,
)
def extract_book_text(self, book_id: str) -> None:
    """Celery wrapper for _run_text_extract."""
    try:
        from app.celeryapp import run_async

        run_async(_run_text_extract(book_id))
    except Exception as exc:
        logger.exception("extract_book_text failed for book %s", book_id)
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
