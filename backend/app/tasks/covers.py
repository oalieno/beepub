"""Thumbnails for the covers stored before there were thumbnails.

A cover gets its thumbnail as it is written (services/storage.py). The
ones already on disk when that came in get theirs here: when the bulk
worker starts, it walks the covers directory once and makes whatever is
missing. On a library that has them all, that is a directory listing
and two stats a cover, and nothing is written.

It runs on start-up, not on a timer: an upgrade (or a restored backup)
is what leaves covers without thumbnails, and both end in a start.
Until it is done the lists show the full cover, as before.
"""

import logging

import redis
from celery.signals import worker_ready

from app.celeryapp import celery
from app.config import settings

logger = logging.getLogger(__name__)

# The walk makes a thumbnail a cover, about a second's work per hundred:
# tens of thousands of covers take a while. It resumes where it stopped,
# so the limits are a backstop, not a deadline.
SOFT_LIMIT_S = 6 * 3600
LOCK_TTL_S = SOFT_LIMIT_S + 600


@celery.task(
    name="app.tasks.covers.make_missing_thumbnails",
    soft_time_limit=SOFT_LIMIT_S,
    time_limit=SOFT_LIMIT_S + 300,
)
def make_missing_thumbnails() -> None:
    from app.services import storage

    client = redis.from_url(settings.redis_url)
    lock = client.lock("beepub:cover-thumbnails", timeout=LOCK_TTL_S)
    if not lock.acquire(blocking=False):
        logger.info("Cover thumbnails: a walk is already under way")
        return
    try:
        seen, made, failed = storage.make_missing_thumbnails(
            settings.covers_dir,
            on_progress=lambda seen, made: logger.info(
                f"Cover thumbnails: {seen} covers looked at, {made} made"
            ),
        )
        if made or failed:
            logger.info(
                f"Cover thumbnails: {seen} covers, {made} made, {failed} failed"
            )
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass  # expired: a later walk may already hold it
        client.close()


@worker_ready.connect
def _start_on_bulk_worker(sender=None, **_kwargs) -> None:
    """Queue the walk once per start, from the bulk worker only (the
    default worker starts beside it and would queue a second)."""
    hostname = getattr(sender, "hostname", "") or ""
    if not hostname.startswith("bulk@"):
        return
    try:
        make_missing_thumbnails.apply_async(queue="bulk")
    except Exception:
        logger.warning("Cover thumbnails: could not queue the walk", exc_info=True)
