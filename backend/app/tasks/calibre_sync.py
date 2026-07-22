"""Celery tasks for automatic Calibre library sync."""

from __future__ import annotations

import logging

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _check_and_sync_calibre() -> None:
    """Gate-check dispatcher: sync any auto-sync library whose metadata.db
    changed since its last sync. Runs every beat tick (60s); the mtime
    gate makes the steady state one file stat per library per minute,
    and the per-book last_modified fast path makes a triggered sync of
    an unchanged library cost seconds — no rate-limit interval needed."""
    import redis.asyncio as aioredis
    from sqlalchemy import select

    from app.config import settings as app_settings
    from app.database import create_task_engine
    from app.models.library import Library
    from app.services.calibre import get_metadata_db_mtime, get_sync_status

    LOCK_KEY = "beepub:calibre:auto_sync_lock"
    LOCK_TTL = 300  # 5 minutes

    client = aioredis.from_url(app_settings.redis_url)
    try:
        # Gate 0: Redis NX lock (prevent concurrent dispatcher runs)
        acquired = await client.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL)
        if not acquired:
            return

        try:
            async with create_task_engine() as (_engine, session_factory):
                async with session_factory() as db:
                    # Query libraries with auto_sync enabled and a calibre path
                    result = await db.execute(
                        select(Library).where(
                            Library.auto_sync.is_(True),
                            Library.calibre_path.isnot(None),
                        )
                    )
                    libraries = result.scalars().all()

                if not libraries:
                    return

                from datetime import UTC, datetime

                now = datetime.now(UTC)

                for lib in libraries:
                    # Gate 1: mtime changed (skip if metadata.db unchanged)
                    mtime = get_metadata_db_mtime(lib.calibre_path)
                    if mtime and lib.last_synced_at and mtime <= lib.last_synced_at:
                        logger.debug(f"No changes for {lib.name}, skipping")
                        continue

                    # Gate 2: Not already running
                    sync_status = await get_sync_status(lib.id)
                    if sync_status and sync_status.get("status") == "running":
                        started_at = sync_status.get("started_at")
                        if started_at:
                            try:
                                started = datetime.fromisoformat(started_at)
                                elapsed = (now - started).total_seconds()
                                if elapsed < 1800:  # 30 min stale threshold
                                    logger.debug(
                                        f"Sync already running for {lib.name}, skipping"
                                    )
                                    continue
                            except (ValueError, TypeError):
                                pass

                    # All gates passed — dispatch per-library sync task
                    logger.info(f"Dispatching auto-sync for {lib.name}")
                    sync_calibre_library.delay(
                        lib.calibre_path,
                        str(lib.id),
                        str(lib.created_by),
                    )
        finally:
            await client.delete(LOCK_KEY)
    finally:
        await client.aclose()


@celery.task(
    name="app.tasks.calibre_sync.check_and_sync_calibre",
    soft_time_limit=6 * 3600,
    time_limit=6 * 3600 + 300,
)
def check_and_sync_calibre() -> None:
    """Celery beat task: periodic calibre sync dispatcher."""
    from app.celeryapp import run_async

    run_async(_check_and_sync_calibre())


@celery.task(
    name="app.tasks.calibre_sync.sync_calibre_library",
    soft_time_limit=6 * 3600,
    time_limit=6 * 3600 + 300,
)
def sync_calibre_library(
    calibre_path: str, library_id: str, admin_user_id: str
) -> None:
    """Celery task: run sync for a single library."""
    import uuid

    from app.celeryapp import run_async
    from app.services.calibre import sync_calibre_library

    run_async(
        sync_calibre_library(
            calibre_path,
            uuid.UUID(library_id),
            uuid.UUID(admin_user_id),
        )
    )
