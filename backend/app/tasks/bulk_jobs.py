"""Unified bulk job orchestrator — dispatches per-book tasks via .delay()."""

from __future__ import annotations

import logging

from celery.exceptions import Ignore

from app.celeryapp import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.bulk_jobs.run_bulk_job", bind=True, acks_late=False)
def run_bulk_job(self, job_type: str, run_id: str) -> None:
    """Orchestrator: query missing book IDs, dispatch per-book tasks, return quickly."""
    from app.celeryapp import run_async

    run_async(_run_bulk_job(job_type, run_id))


async def _run_bulk_job(job_type: str, run_id: str) -> None:
    from app.database import create_task_engine
    from app.services.job_queue import is_run_active

    # Check if this run is still active (may have been stopped before worker picked it up)
    if not await is_run_active(job_type, run_id):
        logger.info("bulk_job %s: run %s no longer active, skipping", job_type, run_id)
        return

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            book_ids = await _get_missing_book_ids(db, job_type)

    total = len(book_ids)
    if total == 0:
        logger.info("bulk_job %s: nothing to do", job_type)
        return

    logger.info("bulk_job %s: dispatching %d tasks (run %s)", job_type, total, run_id)

    for bid in book_ids:
        bid_str = str(bid)
        try:
            _dispatch_single(job_type, bid_str, run_id)
        except Exception:
            logger.exception(
                "bulk_job %s: failed to dispatch for book %s", job_type, bid_str
            )

    logger.info("bulk_job %s: dispatched %d tasks", job_type, total)


@celery.task(name="app.tasks.bulk_jobs.check_run_id")
def check_run_id(job_type: str, run_id: str) -> None:
    """Guard task: skip the rest of the chain if the run has been stopped."""
    from app.celeryapp import run_async
    from app.services.job_queue import is_run_active

    if not run_async(is_run_active(job_type, run_id)):
        raise Ignore()


async def _get_missing_book_ids(db, job_type: str) -> list:
    """Get book IDs that haven't been processed for the given job type."""
    from sqlalchemy import select

    from app.models.book import Book
    from app.models.book_embedding import BookEmbeddingChunk
    from app.models.book_text import BookTextChunk
    from app.models.tag import AiBookTag

    if job_type == "text_extraction":
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        result = await db.execute(
            select(Book.id).where(Book.id.notin_(has_text)).order_by(Book.created_at)
        )
    elif job_type == "embedding":
        # Only books that already have text chunks but no embeddings
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        has_embed = select(BookEmbeddingChunk.book_id).group_by(
            BookEmbeddingChunk.book_id
        )
        result = await db.execute(
            select(Book.id)
            .where(Book.id.in_(has_text), Book.id.notin_(has_embed))
            .order_by(Book.created_at)
        )
    elif job_type == "summarize":
        # Books without text, plus books with unsummarized text chunks
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        no_text_result = await db.execute(
            select(Book.id).where(Book.id.notin_(has_text)).order_by(Book.created_at)
        )
        unsummarized_result = await db.execute(
            select(Book.id)
            .where(Book.id.in_(has_unsummarized))
            .order_by(Book.created_at)
        )
        no_text_ids = [row[0] for row in no_text_result.all()]
        unsummarized_ids = [row[0] for row in unsummarized_result.all()]
        # Deduplicate and preserve order
        seen = set()
        book_ids = []
        for bid in no_text_ids + unsummarized_ids:
            if bid not in seen:
                seen.add(bid)
                book_ids.append(bid)
        return book_ids
    elif job_type == "auto_tag":
        has_tags = select(AiBookTag.book_id).group_by(AiBookTag.book_id)
        result = await db.execute(
            select(Book.id).where(Book.id.notin_(has_tags)).order_by(Book.created_at)
        )
    elif job_type == "word_count":
        result = await db.execute(
            select(Book.id).where(Book.word_count.is_(None)).order_by(Book.created_at)
        )
    else:
        return []

    return [row[0] for row in result.all()]


def _dispatch_single(job_type: str, book_id: str, run_id: str) -> None:
    """Dispatch a per-book task via .delay(), with a run_id guard in front."""
    from celery import chain

    guard = check_run_id.si(job_type, run_id)

    if job_type == "text_extraction":
        from app.tasks.text_extract import extract_book_text

        chain(guard, extract_book_text.si(book_id)).delay()

    elif job_type == "embedding":
        from app.tasks.embed import embed_book
        from app.tasks.text_extract import extract_book_text

        chain(guard, extract_book_text.si(book_id), embed_book.si(book_id)).delay()

    elif job_type == "summarize":
        from app.tasks.summarize import summarize_chunks
        from app.tasks.text_extract import extract_book_text

        chain(
            guard, extract_book_text.si(book_id), summarize_chunks.si(book_id, 999999)
        ).delay()

    elif job_type == "auto_tag":
        from app.tasks.auto_tag import auto_tag_book

        chain(guard, auto_tag_book.si(book_id)).delay()

    elif job_type == "word_count":
        from app.tasks.wordcount import compute_word_count

        chain(guard, compute_word_count.si(book_id)).delay()
