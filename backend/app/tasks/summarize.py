"""Celery task for generating chapter summaries using a cheap LLM."""

from __future__ import annotations

import logging
import re
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")


def _detect_language(text: str) -> str:
    """Detect language from text content using character ratios."""
    sample = text[:5000]
    total = max(len(sample), 1)
    cjk = len(_CJK_RE.findall(sample))
    kana = len(_KANA_RE.findall(sample))
    hangul = len(_HANGUL_RE.findall(sample))

    if kana / total > 0.05:
        return "Japanese (日本語)"
    if hangul / total > 0.05:
        return "Korean (한국어)"
    if cjk / total > 0.1:
        # Detect Traditional vs Simplified by checking common traditional-only chars
        trad_chars = len(
            re.findall(r"[們個這種與對實經過點後發現問題讓說還將從關]", sample)
        )
        if trad_chars > 10:
            return "Traditional Chinese (繁體中文)"
        return "Chinese (中文)"
    return "the same language as the text"


SUMMARY_PROMPT = """\
Summarize this book chapter/section in 2-4 sentences. Focus on key events, \
character actions, and important details. Keep it factual and concise.

CRITICAL: You MUST write the summary in {language}. Do NOT translate to English.

Text:
{text}"""


async def _run_summarize_chunks(
    book_id: str, up_to_spine_index: int | None = None
) -> None:
    """Generate summaries for book text chunks that don't have one yet.

    If up_to_spine_index is None, summarizes all chunks.
    Otherwise, summarizes chunks with spine_index <= up_to_spine_index.
    Does NOT auto-trigger embed_book_summary — caller decides follow-up.
    """
    import redis.asyncio as aioredis
    from sqlalchemy import select

    from app.config import settings
    from app.database import create_task_engine
    from app.models.book import Book
    from app.models.book_text import BookTextChunk
    from app.services.llm import LLMNotConfiguredError, get_tag_provider
    from app.services.settings import get_all_settings

    # Prevent duplicate summarization of the same book
    client = aioredis.from_url(settings.redis_url)
    lock = client.lock(f"summarize:{book_id}", timeout=600)
    if not await lock.acquire(blocking=False):
        logger.info(f"Summarize already running for book {book_id}, skipping")
        await client.aclose()
        return

    try:
        async with create_task_engine() as (_engine, session_factory):
            async with session_factory() as db:
                bid = uuid.UUID(book_id)

                # Skip image books — no meaningful text to summarize
                img_result = await db.execute(
                    select(Book.is_image_book).where(Book.id == bid)
                )
                if img_result.scalar_one_or_none() is True:
                    logger.info(
                        f"Book {book_id} is an image book, skipping summarization"
                    )
                    return

                # Get book language for summary prompt
                book_result = await db.execute(
                    select(Book.epub_language).where(Book.id == bid)
                )
                epub_lang = book_result.scalar_one_or_none()
                if epub_lang and epub_lang.startswith("zh"):
                    book_lang = "Traditional Chinese (繁體中文)"
                elif epub_lang and epub_lang.startswith("ja"):
                    book_lang = "Japanese (日本語)"
                elif epub_lang and epub_lang.startswith("ko"):
                    book_lang = "Korean (한국어)"
                elif epub_lang:
                    book_lang = epub_lang
                else:
                    book_lang = None  # will detect per-chunk below

                # Get chunks that need summaries
                filters = [
                    BookTextChunk.book_id == bid,
                    BookTextChunk.summary.is_(None),
                ]
                if up_to_spine_index is not None:
                    filters.append(BookTextChunk.spine_index <= up_to_spine_index)
                result = await db.execute(
                    select(BookTextChunk)
                    .where(*filters)
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
                    # Skip short/non-content sections
                    if len(stripped) < 1000:
                        chunk.summary = stripped[:200]
                        continue

                    # Truncate very long sections for the summary prompt
                    text = chunk.text
                    if len(text) > 12_000:
                        text = text[:12_000] + "\n\n[...truncated...]"

                    try:
                        lang = book_lang or _detect_language(text)
                        result = await provider.generate(
                            SUMMARY_PROMPT.format(language=lang, text=text),
                        )
                        chunk.summary = result.text.strip()

                        # Log usage (fire-and-forget)
                        from app.services.llm_usage import log_llm_usage

                        await log_llm_usage(
                            feature="summarize",
                            provider=db_settings.get("tag_provider", ""),
                            model=db_settings.get("tag_model", ""),
                            usage=result.usage,
                            book_id=bid,
                            session_factory=session_factory,
                        )
                    except Exception:
                        logger.warning(
                            f"Failed to summarize chunk {chunk.id} (spine {chunk.spine_index}) of book {book_id}",
                            exc_info=True,
                        )
                        # Don't fail the whole task — skip this chunk
                        continue

                await db.commit()
                summarized = sum(1 for c in chunks if c.summary is not None)
                logger.info(
                    f"Summarized {summarized}/{len(chunks)} chunks for book {book_id} (up to spine {up_to_spine_index})"
                )

                # Check if all chunks are now summarized and update flag
                from sqlalchemy import func as sa_func

                unsummarized_result = await db.execute(
                    select(sa_func.count())
                    .select_from(BookTextChunk)
                    .where(
                        BookTextChunk.book_id == bid,
                        BookTextChunk.summary.is_(None),
                    )
                )
                if unsummarized_result.scalar() == 0:
                    from sqlalchemy import update

                    await db.execute(
                        update(Book).where(Book.id == bid).values(is_summarized=True)
                    )
                    await db.commit()
    finally:
        try:
            await lock.release()
        except Exception:
            pass
        await client.aclose()


@celery.task(
    name="app.tasks.summarize.summarize_chunks",
    bind=True,
    max_retries=2,
)
def summarize_chunks(self, book_id: str, up_to_spine_index: int | None = None) -> None:
    """Celery wrapper for _run_summarize_chunks.

    Also auto-triggers embed_book_summary after completion.
    """
    try:
        from app.celeryapp import run_async

        run_async(_run_summarize_chunks(book_id, up_to_spine_index))

        # Auto-embed book summary after summarization completes
        from app.tasks.embed import embed_book_summary

        embed_book_summary.delay(book_id)
    except Exception as exc:
        logger.exception(f"summarize_chunks failed for book {book_id}")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
