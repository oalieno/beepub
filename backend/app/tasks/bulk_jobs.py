"""Unified bulk job orchestrator — dispatches per-book tasks via .delay()."""

from __future__ import annotations

import logging

from app.celeryapp import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.bulk_jobs.run_bulk_job", bind=True, acks_late=False)
def run_bulk_job(self, job_type: str, run_id: str) -> None:
    """Orchestrator: query missing book IDs, dispatch per-book tasks, return quickly."""
    from app.celeryapp import run_async

    run_async(_run_bulk_job(job_type, run_id))


async def _run_bulk_job(job_type: str, run_id: str) -> None:
    from app.database import create_task_engine
    from app.services.job_queue import init_job_progress, is_run_active

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

    # Initialize progress counters in Redis
    await init_job_progress(job_type, run_id, total)

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


@celery.task(name="app.tasks.bulk_jobs.run_book_job", bind=True, max_retries=2)
def run_book_job(self, job_type: str, book_id: str, run_id: str) -> None:
    """Run a single book job: guard check, work, and progress tracking."""
    from app.celeryapp import run_async
    from app.services.job_queue import is_run_active, record_task_completion

    if not run_async(is_run_active(job_type, run_id)):
        return

    try:
        _execute_book_task(job_type, book_id)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
        run_async(record_task_completion(run_id, job_type, success=False))
        logger.exception(
            "run_book_job %s failed for book %s after retries", job_type, book_id
        )
        return

    run_async(record_task_completion(run_id, job_type, success=True))


def _execute_book_task(job_type: str, book_id: str) -> None:
    """Run the actual work for a book. Called inline — no Celery dispatch."""
    from app.celeryapp import run_async

    if job_type == "text_extraction":
        from app.tasks.text_extract import _run_text_extract

        run_async(_run_text_extract(book_id))

    elif job_type == "embedding":
        from app.tasks.embed import _run_embed_book
        from app.tasks.text_extract import _run_text_extract

        run_async(_run_text_extract(book_id))
        run_async(_run_embed_book(book_id))

    elif job_type == "summarize":
        from app.tasks.summarize import _run_summarize_chunks
        from app.tasks.text_extract import _run_text_extract

        run_async(_run_text_extract(book_id))
        run_async(_run_summarize_chunks(book_id, 999999))

    elif job_type == "auto_tag":
        from app.tasks.auto_tag import _run_auto_tag_book

        run_async(_run_auto_tag_book(book_id))

    elif job_type == "book_embedding":
        from app.tasks.embed import _run_embed_book_summary

        run_async(_run_embed_book_summary(book_id))


async def _get_missing_book_ids(db, job_type: str) -> list:
    """Get book IDs that haven't been processed for the given job type."""
    from sqlalchemy import select

    from app.models.book import Book
    from app.models.book_embedding import BookEmbeddingChunk
    from app.models.book_text import BookTextChunk
    from app.models.tag import AiBookTag

    if job_type == "text_extraction":
        # Books without text chunks OR books with chunks but not yet classified
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        no_text_result = await db.execute(
            select(Book.id).where(Book.id.notin_(has_text)).order_by(Book.created_at)
        )
        unclassified_result = await db.execute(
            select(Book.id)
            .where(Book.id.in_(has_text), Book.is_image_book.is_(None))
            .order_by(Book.created_at)
        )
        no_text_ids = [row[0] for row in no_text_result.all()]
        unclassified_ids = [row[0] for row in unclassified_result.all()]
        seen = set()
        book_ids = []
        for bid in no_text_ids + unclassified_ids:
            if bid not in seen:
                seen.add(bid)
                book_ids.append(bid)
        return book_ids
    elif job_type == "embedding":
        # Only non-image books that already have text chunks but no embeddings
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        has_embed = select(BookEmbeddingChunk.book_id).group_by(
            BookEmbeddingChunk.book_id
        )
        result = await db.execute(
            select(Book.id)
            .where(
                Book.id.in_(has_text),
                Book.id.notin_(has_embed),
                Book.is_image_book.isnot(True),
            )
            .order_by(Book.created_at)
        )
    elif job_type == "summarize":
        # Non-image books without text, plus non-image books with unsummarized chunks
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        no_text_result = await db.execute(
            select(Book.id)
            .where(Book.id.notin_(has_text), Book.is_image_book.isnot(True))
            .order_by(Book.created_at)
        )
        unsummarized_result = await db.execute(
            select(Book.id)
            .where(Book.id.in_(has_unsummarized), Book.is_image_book.isnot(True))
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
    elif job_type == "book_embedding":
        # Books with ALL chunks summarized but no BookEmbedding row, excluding image books
        from app.models.book_embedding_unified import BookEmbedding

        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        fully_summarized = (
            select(BookTextChunk.book_id)
            .group_by(BookTextChunk.book_id)
            .except_(has_unsummarized)
        )
        has_book_embed = select(BookEmbedding.book_id)
        result = await db.execute(
            select(Book.id)
            .where(
                Book.id.in_(fully_summarized),
                Book.id.notin_(has_book_embed),
                Book.is_image_book.isnot(True),
            )
            .order_by(Book.created_at)
        )
    else:
        return []

    return [row[0] for row in result.all()]


def _dispatch_single(job_type: str, book_id: str, run_id: str) -> None:
    """Dispatch a single book job task."""
    run_book_job.delay(job_type, book_id, run_id)
