"""Celery task for generating chapter summaries using a cheap LLM."""

from __future__ import annotations

import logging
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """\
Summarize this book chapter/section in 2-4 sentences. Focus on key events, \
character actions, and important details. Keep it factual and concise.

CRITICAL: You MUST write the summary in {language}. Do NOT translate to English.

Text:
{text}"""


@celery.task(
    name="app.tasks.summarize.summarize_chunks",
    bind=True,
    max_retries=2,
)
def summarize_chunks(self, book_id: str, up_to_spine_index: int) -> None:
    """Generate summaries for book text chunks that don't have one yet.

    Summarizes all chunks with spine_index <= up_to_spine_index.
    """
    import asyncio

    async def _run() -> None:
        from sqlalchemy import select

        from app.database import create_task_session
        from app.models.book import Book
        from app.models.book_text import BookTextChunk
        from app.services.llm import LLMNotConfiguredError, get_tag_provider
        from app.services.settings import get_all_settings

        session_factory = create_task_session()
        async with session_factory() as db:
            bid = uuid.UUID(book_id)

            # Get book language for summary prompt
            book_result = await db.execute(
                select(Book.epub_language).where(Book.id == bid)
            )
            book_lang = (
                book_result.scalar_one_or_none() or "the same language as the text"
            )

            # Get chunks that need summaries
            result = await db.execute(
                select(BookTextChunk)
                .where(
                    BookTextChunk.book_id == bid,
                    BookTextChunk.spine_index <= up_to_spine_index,
                    BookTextChunk.summary.is_(None),
                )
                .order_by(BookTextChunk.spine_index)
            )
            chunks = result.scalars().all()

            if not chunks:
                return

            # Get LLM provider
            db_settings = await get_all_settings(db)
            try:
                provider = get_tag_provider(db_settings)
            except LLMNotConfiguredError:
                logger.warning("Tag AI not configured, skipping summarization")
                return

            for chunk in chunks:
                stripped = chunk.text.strip()
                # Skip very short sections (likely title pages, etc.)
                if len(stripped) < 200:
                    chunk.summary = stripped
                    continue

                # Skip TOC-like pages: mostly short lines (chapter listings)
                lines = [ln for ln in stripped.split("\n") if ln.strip()]
                avg_line_len = len(stripped) / max(len(lines), 1)
                if avg_line_len < 30 and len(lines) > 5:
                    chunk.summary = stripped[:200]
                    continue

                # Truncate very long sections for the summary prompt
                text = chunk.text
                if len(text) > 12_000:
                    text = text[:12_000] + "\n\n[...truncated...]"

                try:
                    summary = await provider.generate(
                        SUMMARY_PROMPT.format(language=book_lang, text=text),
                    )
                    chunk.summary = summary.strip()
                except Exception:
                    logger.warning(
                        "Failed to summarize chunk %s (spine %d) of book %s",
                        chunk.id,
                        chunk.spine_index,
                        book_id,
                        exc_info=True,
                    )
                    # Don't fail the whole task — skip this chunk
                    continue

            await db.commit()
            summarized = sum(1 for c in chunks if c.summary is not None)
            logger.info(
                "Summarized %d/%d chunks for book %s (up to spine %d)",
                summarized,
                len(chunks),
                book_id,
                up_to_spine_index,
            )

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.exception("summarize_chunks failed for book %s", book_id)
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
