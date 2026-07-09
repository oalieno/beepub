"""Backfill KOReader partial-MD5 digests for books that predate kosync.

New uploads and calibre syncs compute the digest inline; this periodic
task covers everything that existed before, and self-heals rows whose
file went temporarily missing. It exits immediately when there is
nothing to do, so the short beat interval is cheap.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.celeryapp import celery

logger = logging.getLogger(__name__)

_BATCH_SIZE = 200


async def _run_backfill() -> int:
    from app.database import create_task_engine
    from app.models.book import Book
    from app.services.partial_md5 import compute_partial_md5

    filled = 0
    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            result = await db.execute(
                select(Book.id, Book.file_path)
                .where(Book.partial_md5.is_(None))
                .limit(_BATCH_SIZE)
            )
            rows = result.all()
            if not rows:
                return 0
            for book_id, file_path in rows:
                digest = await asyncio.to_thread(compute_partial_md5, file_path)
                if digest is None:
                    continue
                book = (
                    await db.execute(select(Book).where(Book.id == book_id))
                ).scalar_one_or_none()
                if book is not None:
                    book.partial_md5 = digest
                    filled += 1
            await db.commit()
    return filled


@celery.task(name="app.tasks.digests.backfill_partial_md5")
def backfill_partial_md5() -> None:
    from app.celeryapp import run_async

    filled = run_async(_run_backfill())
    if filled:
        logger.info(f"Backfilled partial_md5 for {filled} books")
