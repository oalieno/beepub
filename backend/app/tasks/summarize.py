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


@celery.task(
    name="app.tasks.summarize.summarize_chunks",
    bind=True,
    max_retries=2,
)
def summarize_chunks(self, book_id: str, up_to_spine_index: int) -> None:
    """Generate summaries for book text chunks that don't have one yet.

    Summarizes all chunks with spine_index <= up_to_spine_index.
    """

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
                # Skip short/non-content sections (title pages, copyright, TOC, etc.)
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
        from app.celeryapp import run_async

        run_async(_run())
    except Exception as exc:
        logger.exception("summarize_chunks failed for book %s", book_id)
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
