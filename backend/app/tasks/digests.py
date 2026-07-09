"""KOReader digest computation — a bulk job type with an automatic kick.

"digest" is a regular bulk job: visible in Admin → Jobs with missing and
pending counts, manually runnable and stoppable, one book per task on the
bulk queue (see bulk_jobs._TASK_REGISTRY). The beat task here only
auto-starts that job when books lack digests and no run is in flight, so
an upgrade backfills a whole library without anyone clicking — while the
admin UI still shows and controls the run.

Unreadable files get an empty-string digest so they leave the missing
count instead of being retried forever (a 32-hex kosync document can
never match ""); calibre sync recomputes when the file comes back with a
newer mtime.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _run_book_digest(book_id: str) -> None:
    """Bulk-job step: digest one book, then apply any waiting kosync records."""
    from app.database import create_task_engine
    from app.models.book import Book
    from app.services.kosync_bridge import retro_bridge_document
    from app.services.partial_md5 import compute_partial_md5

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            book = (
                await db.execute(select(Book).where(Book.id == uuid.UUID(book_id)))
            ).scalar_one_or_none()
            if book is None or book.partial_md5 is not None:
                return
            digest = await asyncio.to_thread(compute_partial_md5, book.file_path)
            book.partial_md5 = digest or ""
            if digest:
                bridged = await retro_bridge_document(db, book.id, digest)
                if bridged:
                    logger.info(
                        f"Digest for book {book_id} bridged {bridged} waiting "
                        "kosync records"
                    )
            await db.commit()


async def _auto_kick() -> bool:
    """Start the digest bulk job iff there is work and nothing in flight.

    A race with a manual trigger is tolerated: the generation guard makes
    the older orchestrator exit early.
    """
    from app.database import create_task_engine
    from app.models.book import Book
    from app.services.job_queue import get_pending_count, start_job

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            missing = await db.scalar(
                select(func.count()).select_from(Book).where(Book.partial_md5.is_(None))
            )
    if not missing:
        return False
    if await get_pending_count("digest") > 0:
        return False

    generation = await start_job("digest")
    from app.tasks.bulk_jobs import run_bulk_job

    run_bulk_job.delay("digest", generation)
    logger.info(
        f"Auto-started digest job for {missing} books (generation {generation})"
    )
    return True


@celery.task(name="app.tasks.digests.backfill_partial_md5")
def backfill_partial_md5() -> None:
    from app.celeryapp import run_async

    run_async(_auto_kick())
