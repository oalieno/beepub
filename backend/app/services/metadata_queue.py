import json
import uuid

import redis.asyncio as redis

from app.config import settings

QUEUE_KEY = "beepub:metadata:queue"


async def get_queue_length() -> int:
    """Get the number of pending metadata jobs in the queue."""
    client = redis.from_url(settings.redis_url)
    try:
        return await client.llen(QUEUE_KEY)
    finally:
        await client.aclose()


async def push_metadata_job(book_id: uuid.UUID, priority: str = "normal") -> None:
    """Push a metadata fetch job to Redis queue."""
    client = redis.from_url(settings.redis_url)
    try:
        payload = json.dumps({"book_id": str(book_id), "priority": priority})
        if priority == "high":
            await client.lpush(QUEUE_KEY, payload)
        else:
            await client.rpush(QUEUE_KEY, payload)
    finally:
        await client.aclose()
