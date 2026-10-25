"""Celery task for extracting text from EPUB files into DB chunks."""

from __future__ import annotations

import logging
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _run_extract_book_text(book_id: str) -> None:
    """Extract text from an EPUB and store as BookTextChunk rows.

    Also computes word_count and is_image_book: at least 80% of the linear
    spine items are picture pages (see epub_text.SpinePictures). When chunks
    already exist, word_count comes from them, but the classification still
    opens the EPUB: a picture page has no chunk, so the chunks cannot count
    them.
    """
    import asyncio

    from sqlalchemy import select, update

    from app.database import create_task_engine
    from app.models.book import Book
    from app.models.book_text import BookTextChunk
    from app.services.epub_text import (
        classify_image_book,
        count_words_from_chunks,
        count_words_from_texts,
        extract_book_text,
    )

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            bid = uuid.UUID(book_id)

            # Check if already extracted
            existing = await db.execute(
                select(BookTextChunk.id).where(BookTextChunk.book_id == bid).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                # Chunks exist — ensure has_text flag is set
                await db.execute(
                    update(Book).where(Book.id == bid).values(has_text=True)
                )

                # Check if classification is needed
                book_row = await db.execute(
                    select(Book.word_count, Book.is_image_book).where(Book.id == bid)
                )
                row = book_row.one_or_none()
                current_wc = row[0] if row else None
                current_is_image = row[1] if row else None

                if current_wc is not None and current_is_image is not None:
                    # Already fully classified, nothing to do
                    await db.commit()
                    return

                if current_wc is None:
                    # word_count is NULL — count it from stored DB chunks
                    chunk_texts_result = await db.execute(
                        select(BookTextChunk.text).where(BookTextChunk.book_id == bid)
                    )
                    texts = [row[0] for row in chunk_texts_result.all()]
                    current_wc = count_words_from_texts(texts)

                path_row = await db.execute(
                    select(Book.file_path).where(Book.id == bid)
                )
                file_path = path_row.scalar_one_or_none()
                try:
                    is_image = await asyncio.to_thread(classify_image_book, file_path)
                except Exception:
                    # Unreadable now, but its text was read once: a text
                    # book, which the reader can always show (NULL would
                    # queue it again forever).
                    logger.warning(
                        f"Failed to open EPUB for book {book_id}, classifying as text",
                        exc_info=True,
                    )
                    is_image = False

                await db.execute(
                    update(Book)
                    .where(Book.id == bid)
                    .values(word_count=current_wc, is_image_book=is_image)
                )
                await db.commit()
                logger.info(
                    f"Classified book {book_id}: word_count={current_wc}, is_image_book={is_image}"
                )
                return

            # Fresh extraction path
            result = await db.execute(select(Book.file_path).where(Book.id == bid))
            row = result.one_or_none()
            if not row:
                logger.warning(f"Book {book_id} not found, skipping text extraction")
                return

            file_path = row[0]
            try:
                extracted = await asyncio.to_thread(
                    extract_book_text, file_path, max_chars=10_000_000
                )
            except Exception as exc:
                # Corrupt/unreadable EPUB — classify and auto-report
                logger.warning(
                    f"Failed to parse EPUB for book {book_id}, classifying as image book",
                    exc_info=True,
                )
                await db.execute(
                    update(Book)
                    .where(Book.id == bid)
                    .values(word_count=0, is_image_book=True)
                )
                try:
                    from app.models.book_report import BookReport

                    db.add(
                        BookReport(
                            book_id=bid,
                            issue_type="corrupt_file",
                            description=str(exc)[:500],
                        )
                    )
                except Exception:
                    logger.warning(
                        f"Failed to create report for corrupt book {book_id}"
                    )
                await db.commit()
                return

            chunks = extracted.chunks
            if not chunks:
                # No text at all — classify as image book
                await db.execute(
                    update(Book)
                    .where(Book.id == bid)
                    .values(word_count=0, is_image_book=True)
                )
                await db.commit()
                logger.info(f"Book {book_id} has no text, classified as image book")
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

            # Word count from the extracted chunks; the class from the spine
            wc = count_words_from_chunks(chunks)
            is_image = extracted.pictures.is_image_book

            await db.execute(
                update(Book)
                .where(Book.id == bid)
                .values(word_count=wc, is_image_book=is_image, has_text=True)
            )

            await db.commit()
            logger.info(
                f"Extracted {len(chunks)} text chunks from book {book_id} (word_count={wc}, is_image_book={is_image})"
            )


@celery.task(
    name="app.tasks.text_extract.extract_book_text",
    bind=True,
    max_retries=2,
)
def extract_book_text(self, book_id: str) -> None:
    """Celery wrapper for _run_extract_book_text."""
    try:
        from app.celeryapp import run_async

        run_async(_run_extract_book_text(book_id))
    except Exception as exc:
        logger.exception(f"extract_book_text failed for book {book_id}")
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
