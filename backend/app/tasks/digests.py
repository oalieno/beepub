"""Backfill KOReader partial-MD5 digests for books that predate kosync.

New uploads and calibre syncs compute the digest inline; this task covers
everything that existed before. Each run processes one batch and, when the
batch was full, re-enqueues itself — a large library drains in one
continuous chain instead of one batch per beat tick (63k books would
otherwise take days). The beat schedule remains as the restart-safe kick.

Unreadable files are marked with an empty-string digest so they are not
re-selected forever (a 32-hex kosync document can never match ""); the
calibre sync recomputes when a file comes back with a newer mtime.

Books that gain a digest are retro-bridged: kosync progress that arrived
before the digest existed (typical for the first sync after upgrading)
is applied to reading progress immediately instead of waiting for the
device's next push.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.celeryapp import celery

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500


async def _retro_bridge(db, digest_to_books: dict[str, list]) -> int:
    """Apply stored kosync records whose document just gained a book."""
    from app.models.kosync import KosyncProgress
    from app.models.library import Library, LibraryBook, UserLibraryExclusion
    from app.services.kosync_bridge import bridge_kosync_percentage

    if not digest_to_books:
        return 0
    records = (
        (
            await db.execute(
                select(KosyncProgress).where(
                    KosyncProgress.document.in_(digest_to_books.keys()),
                    KosyncProgress.percentage.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    bridged = 0
    for record in records:
        for book_id in digest_to_books[record.document]:
            # Mirror the router's access rule: skip books whose library is
            # excluded for this user (admins have no exclusions in practice;
            # the exclusion table is authoritative either way).
            excluded = (
                await db.execute(
                    select(UserLibraryExclusion.library_id)
                    .join(Library, Library.id == UserLibraryExclusion.library_id)
                    .join(LibraryBook, LibraryBook.library_id == Library.id)
                    .where(
                        UserLibraryExclusion.user_id == record.user_id,
                        LibraryBook.book_id == book_id,
                    )
                )
            ).first()
            if excluded:
                continue
            await bridge_kosync_percentage(
                db, record.user_id, book_id, record.percentage
            )
            bridged += 1
    return bridged


async def _run_backfill() -> int:
    """Process one batch; returns the number of rows selected."""
    from app.database import create_task_engine
    from app.models.book import Book
    from app.services.partial_md5 import compute_partial_md5

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

            digest_to_books: dict[str, list] = {}
            filled = 0
            for book_id, file_path in rows:
                digest = await asyncio.to_thread(compute_partial_md5, file_path)
                book = (
                    await db.execute(select(Book).where(Book.id == book_id))
                ).scalar_one_or_none()
                if book is None:
                    continue
                book.partial_md5 = digest or ""
                if digest:
                    filled += 1
                    digest_to_books.setdefault(digest, []).append(book_id)

            bridged = await _retro_bridge(db, digest_to_books)
            await db.commit()

    logger.info(
        f"Digest backfill: {filled}/{len(rows)} filled, {bridged} kosync "
        "records bridged"
    )
    return len(rows)


@celery.task(name="app.tasks.digests.backfill_partial_md5")
def backfill_partial_md5() -> None:
    from app.celeryapp import run_async

    processed = run_async(_run_backfill())
    if processed >= _BATCH_SIZE:
        # Full batch — more work is likely waiting; drain continuously.
        backfill_partial_md5.delay()
