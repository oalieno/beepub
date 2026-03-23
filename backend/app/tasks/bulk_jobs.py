"""Unified bulk job orchestrator — processes books in batches with Redis progress tracking."""

from __future__ import annotations

import logging

from app.celeryapp import celery

logger = logging.getLogger(__name__)

BATCH_SIZE = 10


@celery.task(name="app.tasks.bulk_jobs.run_bulk_job", bind=True, acks_late=False)
def run_bulk_job(self, job_type: str, mode: str = "missing") -> None:
    """Orchestrator task: iterate books in batches, call per-book task, track progress."""
    from app.celeryapp import run_async

    run_async(_run_bulk_job(job_type, mode))


async def _run_bulk_job(job_type: str, mode: str) -> None:
    from sqlalchemy import select

    from app.database import create_task_session
    from app.models.book import Book
    from app.services.job_queue import get_job_status, set_job_status

    # Skip if another instance is already running (e.g. redelivered after worker restart)
    current = await get_job_status(job_type)
    if current and current.get("status") == "running":
        logger.info("bulk_job %s already running, skipping duplicate", job_type)
        return
    # Also skip if cancelled before worker even picked it up
    if current and current.get("status") == "cancelled":
        logger.info("bulk_job %s was cancelled before starting, skipping", job_type)
        return

    session_factory = create_task_session()
    async with session_factory() as db:
        # Get book IDs based on mode
        if mode == "all":
            result = await db.execute(select(Book.id).order_by(Book.created_at))
            book_ids = [row[0] for row in result.all()]
        else:
            # "missing" mode — only books that need processing
            book_ids = await _get_missing_book_ids(db, job_type)

    total = len(book_ids)
    if total == 0:
        logger.info("bulk_job %s (%s): nothing to do", job_type, mode)
        await set_job_status(job_type, status="completed", total=0, processed=0)
        return

    logger.info("bulk_job %s (%s): %d books to process", job_type, mode, total)
    await set_job_status(job_type, status="running", total=total, processed=0)

    processed = 0
    failed = 0

    try:
        for i in range(0, total, BATCH_SIZE):
            batch = book_ids[i : i + BATCH_SIZE]

            for bid in batch:
                bid_str = str(bid)
                try:
                    _dispatch_single(job_type, bid_str)
                except Exception:
                    logger.exception(
                        "bulk_job %s: failed for book %s, skipping", job_type, bid_str
                    )
                    failed += 1

                processed += 1

            # Check for cancellation before updating progress — if cancelled,
            # don't overwrite the "cancelled" status back to "running"
            current = await get_job_status(job_type)
            if current and current.get("status") == "cancelled":
                logger.info(
                    "bulk_job %s cancelled at %d/%d", job_type, processed, total
                )
                return

            await set_job_status(
                job_type,
                status="running",
                total=total,
                processed=processed,
                failed=failed,
            )
            logger.info("bulk_job %s progress: %d/%d", job_type, processed, total)

        await set_job_status(
            job_type,
            status="completed",
            total=total,
            processed=processed,
            failed=failed,
        )
        logger.info(
            "bulk_job %s complete: %d processed, %d failed",
            job_type,
            processed,
            failed,
        )
    except Exception:
        logger.exception("bulk_job %s crashed at %d/%d", job_type, processed, total)
        await set_job_status(
            job_type,
            status="failed",
            total=total,
            processed=processed,
            failed=failed,
        )


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
        # All books without embeddings (orchestrator handles text extraction as prerequisite)
        has_embed = select(BookEmbeddingChunk.book_id).group_by(
            BookEmbeddingChunk.book_id
        )
        result = await db.execute(
            select(Book.id).where(Book.id.notin_(has_embed)).order_by(Book.created_at)
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
    elif job_type == "summary_embedding":
        from app.models.book_summary_embedding import BookSummaryEmbedding

        has_summary = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.isnot(None))
            .group_by(BookTextChunk.book_id)
        )
        has_embed = select(BookSummaryEmbedding.book_id)
        result = await db.execute(
            select(Book.id)
            .where(Book.id.in_(has_summary.except_(has_embed)))
            .order_by(Book.created_at)
        )
    else:
        return []

    return [row[0] for row in result.all()]


def _dispatch_single(job_type: str, book_id: str) -> None:
    """Call the per-book task synchronously (within the orchestrator)."""
    if job_type == "text_extraction":
        from app.tasks.text_extract import extract_book_text

        extract_book_text(book_id)

    elif job_type == "embedding":
        from app.tasks.embed import embed_book
        from app.tasks.text_extract import extract_book_text

        # Ensure text is extracted first (prerequisite for embedding)
        extract_book_text(book_id)
        embed_book(book_id)

    elif job_type == "summarize":
        from app.tasks.summarize import summarize_chunks
        from app.tasks.text_extract import extract_book_text

        # Ensure text is extracted first (prerequisite for summarization)
        extract_book_text(book_id)
        summarize_chunks(book_id, up_to_spine_index=999999)

    elif job_type == "auto_tag":
        from app.tasks.auto_tag import auto_tag_book

        auto_tag_book(book_id)

    elif job_type == "word_count":
        from app.tasks.wordcount import compute_word_count

        compute_word_count(book_id)

    elif job_type == "summary_embedding":
        from app.tasks.embed import embed_book_summary

        embed_book_summary(book_id)
