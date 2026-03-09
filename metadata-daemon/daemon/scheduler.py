import json
import logging
from datetime import UTC, datetime

import redis.asyncio as redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from zoneinfo import ZoneInfo

from daemon.config import settings
from daemon.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

QUEUE_KEY = "beepub:metadata:queue"
LAST_SCHEDULED_KEY = "beepub:metadata:last_scheduled"


async def _get_setting(db, key: str, default: str = "") -> str:
    result = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :key"),
        {"key": key},
    )
    row = result.one_or_none()
    return row[0] if row else default


async def check_and_schedule() -> None:
    """Hourly check: read settings from DB and queue books if conditions are met."""
    async with AsyncSessionLocal() as db:
        enabled = await _get_setting(db, "metadata_refresh_enabled", "true")
        if enabled != "true":
            return

        tz_name = await _get_setting(db, "timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")

        now_local = datetime.now(tz)
        refresh_hour = int(await _get_setting(db, "metadata_refresh_hour", "3"))
        if now_local.hour != refresh_hour:
            return

        interval_days = int(
            await _get_setting(db, "metadata_refresh_interval_days", "7")
        )
        cooldown_days = int(
            await _get_setting(db, "metadata_refresh_cooldown_days", "30")
        )

    # Check if we already ran within the interval
    client = redis.from_url(settings.redis_url)
    try:
        last_run = await client.get(LAST_SCHEDULED_KEY)
        if last_run:
            last_run_dt = datetime.fromisoformat(last_run.decode())
            days_since = (datetime.now(UTC) - last_run_dt).total_seconds() / 86400
            if days_since < interval_days:
                logger.debug(
                    f"Last scheduled {days_since:.1f} days ago, "
                    f"interval is {interval_days} days, skipping"
                )
                return

        # Query books that need refresh (never fetched or cooldown expired)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT b.id FROM books b
                    LEFT JOIN (
                        SELECT book_id, MAX(fetched_at) as last_fetched
                        FROM external_metadata GROUP BY book_id
                    ) em ON em.book_id = b.id
                    WHERE em.last_fetched IS NULL
                       OR em.last_fetched < NOW() - MAKE_INTERVAL(days => :cooldown)
                """),
                {"cooldown": cooldown_days},
            )
            book_ids = [str(row[0]) for row in result.fetchall()]

        if not book_ids:
            logger.info("No books need metadata refresh")
        else:
            for book_id in book_ids:
                payload = json.dumps({"book_id": book_id, "priority": "normal"})
                await client.rpush(QUEUE_KEY, payload)
            logger.info(f"Queued {len(book_ids)} books for metadata refresh")

        # Record last scheduled time
        await client.set(LAST_SCHEDULED_KEY, datetime.now(UTC).isoformat())
    finally:
        await client.aclose()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_schedule,
        "interval",
        hours=1,
        id="metadata_refresh_check",
    )
    return scheduler
