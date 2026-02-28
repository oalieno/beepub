import json
import logging
from datetime import datetime, timezone

import redis.asyncio as redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from daemon.config import settings
from daemon.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

QUEUE_KEY = "beepub:metadata:queue"


async def schedule_all_books() -> None:
    """Push all books to metadata queue for daily refresh."""
    logger.info("Scheduling daily metadata refresh for all books")
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT id FROM books"))
        book_ids = [str(row[0]) for row in result.fetchall()]

    client = redis.from_url(settings.redis_url)
    try:
        for book_id in book_ids:
            payload = json.dumps({"book_id": book_id, "priority": "normal"})
            await client.rpush(QUEUE_KEY, payload)
        logger.info(f"Queued {len(book_ids)} books for metadata refresh")
    finally:
        await client.aclose()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        schedule_all_books,
        "cron",
        hour=3,
        minute=0,
        id="daily_metadata_refresh",
    )
    return scheduler
