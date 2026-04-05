"""Unified bulk job orchestrator — dispatches per-book tasks via .delay()."""

from __future__ import annotations

import logging

from app.celeryapp import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.bulk_jobs.run_bulk_job", bind=True, acks_late=False)
def run_bulk_job(self, job_type: str, generation: int) -> None:
    """Orchestrator: query missing book IDs, dispatch per-book tasks, return quickly."""
    from app.celeryapp import run_async

    run_async(_run_bulk_job(job_type, generation))


async def _run_bulk_job(job_type: str, generation: int) -> None:
    from app.database import create_task_engine
    from app.services.job_queue import incr_pending, is_current_generation

    # Check if this generation is still current (may have been stopped)
    if not await is_current_generation(job_type, generation):
        logger.info(f"bulk_job {job_type}: generation {generation} is stale, skipping")
        return

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            book_ids = await _get_missing_book_ids(db, job_type)

    total = len(book_ids)
    if total == 0:
        logger.info(f"bulk_job {job_type}: nothing to do")
        return

    # Set pending count upfront
    await incr_pending(job_type, total)

    logger.info(
        f"bulk_job {job_type}: dispatching {total} tasks (generation {generation})"
    )

    for bid in book_ids:
        bid_str = str(bid)
        try:
            run_book_job.delay(job_type, bid_str, generation)
        except Exception:
            logger.exception(
                f"bulk_job {job_type}: failed to dispatch for book {bid_str}"
            )

    logger.info(f"bulk_job {job_type}: dispatched {total} tasks")


@celery.task(name="app.tasks.bulk_jobs.run_book_job", bind=True, max_retries=2)
def run_book_job(self, job_type: str, book_id: str, generation: int) -> None:
    """Run a single book job: generation guard, pending tracking, work."""
    from app.celeryapp import run_async
    from app.services.job_queue import decr_pending, is_current_generation

    # Skip if generation is stale (job was stopped)
    if not run_async(is_current_generation(job_type, generation)):
        return

    try:
        _execute_book_task(job_type, book_id)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
        logger.exception(
            f"run_book_job {job_type} failed for book {book_id} after retries"
        )
    finally:
        run_async(decr_pending(job_type))


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

    elif job_type == "metadata_backfill":
        from app.tasks.metadata_backfill import _run_metadata_backfill

        run_async(_run_metadata_backfill(book_id))

    elif job_type == "auto_tag":
        from app.tasks.auto_tag import _run_auto_tag_book

        run_async(_run_auto_tag_book(book_id))

    elif job_type == "book_embedding":
        from app.tasks.embed import _run_embed_book_summary

        run_async(_run_embed_book_summary(book_id))


async def _get_missing_book_ids(db, job_type: str) -> list:
    """Get book IDs that haven't been processed for the given job type."""
    from sqlalchemy import func, select

    from app.models.book import Book
    from app.models.book_embedding import BookEmbeddingChunk
    from app.models.book_text import BookTextChunk
    from app.models.tag import BookTag

    if job_type == "text_extraction":
        result = await db.execute(
            select(Book.id)
            .where(Book.is_image_book.is_(None))
            .order_by(Book.created_at)
        )
    elif job_type == "embedding":
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
        seen = set()
        book_ids = []
        for bid in no_text_ids + unsummarized_ids:
            if bid not in seen:
                seen.add(bid)
                book_ids.append(bid)
        return book_ids
    elif job_type == "metadata_backfill":
        from app.models.book import ExternalMetadata

        fully_fetched = (
            select(ExternalMetadata.book_id)
            .group_by(ExternalMetadata.book_id)
            .having(func.count(ExternalMetadata.source) >= 4)
        )
        result = await db.execute(
            select(Book.id)
            .where(Book.id.notin_(fully_fetched))
            .order_by(Book.created_at)
        )
    elif job_type == "auto_tag":
        has_tags = select(BookTag.book_id).group_by(BookTag.book_id)
        result = await db.execute(
            select(Book.id).where(Book.id.notin_(has_tags)).order_by(Book.created_at)
        )
    elif job_type == "book_embedding":
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
