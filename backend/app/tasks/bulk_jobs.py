"""Unified bulk job orchestrator — dispatches per-book tasks via .delay()."""

from __future__ import annotations

import logging

from app.celeryapp import celery

logger = logging.getLogger(__name__)

# Registry: job_type → list of (module_path, function_name) to call in order.
# Each function is called with (book_id: str) via run_async().
_TASK_REGISTRY: dict[str, list[tuple[str, str]]] = {
    "text_extraction": [
        ("app.tasks.text_extract", "_run_extract_book_text"),
    ],
    "embedding": [
        ("app.tasks.text_extract", "_run_extract_book_text"),
        ("app.tasks.embed", "_run_embed_book"),
    ],
    "summarize": [
        ("app.tasks.text_extract", "_run_extract_book_text"),
        ("app.tasks.summarize", "_run_summarize_chunks"),
    ],
    "metadata_backfill": [
        ("app.tasks.metadata", "_run_fetch_book_metadata"),
    ],
    "auto_tag": [
        ("app.tasks.auto_tag", "_run_auto_tag_book"),
    ],
    "book_embedding": [
        ("app.tasks.embed", "_run_embed_book_summary"),
    ],
}


@celery.task(name="app.tasks.bulk_jobs.run_bulk_job", bind=True, acks_late=False)
def run_bulk_job(self, job_type: str, generation: int) -> None:
    """Orchestrator: query missing book IDs, dispatch per-book tasks, return quickly."""
    from app.celeryapp import run_async

    run_async(_run_bulk_job(job_type, generation))


async def _run_bulk_job(job_type: str, generation: int) -> None:
    from app.database import create_task_engine
    from app.services.job_queue import (
        get_missing_book_ids,
        incr_pending,
        is_current_generation,
    )

    # Check if this generation is still current (may have been stopped)
    if not await is_current_generation(job_type, generation):
        logger.info(f"bulk_job {job_type}: generation {generation} is stale, skipping")
        return

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            book_ids = await get_missing_book_ids(db, job_type)

    total = len(book_ids)
    if total == 0:
        logger.info(f"bulk_job {job_type}: nothing to do")
        return

    # Set pending count upfront
    pending_val = await incr_pending(job_type, total)

    logger.info(
        f"bulk_job {job_type}: dispatching {total} tasks (generation {generation}), pending set to {pending_val}"
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
        # Don't decr — stop_job already reset pending to 0
        return

    try:
        _execute_book_task(job_type, book_id)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            # Don't decr pending — the retry will handle it
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
        logger.exception(
            f"run_book_job {job_type} failed for book {book_id} after retries"
        )
    pending_after = run_async(decr_pending(job_type))
    logger.info(
        f"run_book_job {job_type} book {book_id} done, pending now {pending_after}"
    )


def _execute_book_task(job_type: str, book_id: str) -> None:
    """Run the actual work for a book. Called inline — no Celery dispatch."""
    import importlib

    from app.celeryapp import run_async

    steps = _TASK_REGISTRY.get(job_type)
    if not steps:
        return

    for module_path, func_name in steps:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        if func_name == "_run_summarize_chunks":
            run_async(fn(book_id, None))  # None = all chapters
        else:
            run_async(fn(book_id))
