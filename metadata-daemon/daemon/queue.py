import json
import logging
from datetime import UTC, datetime

import redis.asyncio as redis

from daemon.config import settings
from daemon.database import AsyncSessionLocal
from daemon.sources.goodreads import GoodreadsSource
from daemon.sources.readmoo import ReadmooSource

logger = logging.getLogger(__name__)

QUEUE_KEY = "beepub:metadata:queue"

SOURCES = [GoodreadsSource(), ReadmooSource()]


async def process_job(book_id: str) -> None:
    """Fetch metadata from all sources for the given book_id."""
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        # Get book info
        result = await db.execute(
            text(
                "SELECT id, epub_title, epub_authors, epub_isbn, title, authors "
                "FROM books WHERE id = :id"
            ),
            {"id": book_id},
        )
        row = result.mappings().one_or_none()
        if not row:
            logger.warning(f"Book {book_id} not found, skipping")
            return

        display_title = row["title"] or row["epub_title"] or ""
        display_authors = row["authors"] or row["epub_authors"] or []
        isbn = row["epub_isbn"]

        if not display_title:
            logger.info(f"Book {book_id} has no title, skipping metadata fetch")
            return

        for source in SOURCES:
            try:
                # Check for manually pinned URL
                existing = await db.execute(
                    text(
                        "SELECT source_url FROM external_metadata "
                        "WHERE book_id = :book_id AND source = :source"
                    ),
                    {"book_id": book_id, "source": source.source_name},
                )
                existing_row = existing.mappings().one_or_none()
                pinned_url = existing_row["source_url"] if existing_row else None

                if pinned_url:
                    # Skip search, fetch directly from pinned URL
                    logger.info(
                        "Using pinned URL for %s book %s: %s",
                        source.source_name, book_id, pinned_url,
                    )
                    fetch_result = await source.fetch(pinned_url)
                    source_url = pinned_url
                else:
                    results = await source.search(
                        display_title, display_authors, isbn
                    )
                    if not results:
                        logger.info(
                            f"No results from {source.source_name} for book {book_id}"
                        )
                        continue

                    best = results[0]
                    fetch_result = await source.fetch(best.url)
                    source_url = fetch_result.source_url

                # Upsert external_metadata
                await db.execute(
                    text(
                        """
                        INSERT INTO external_metadata
                            (
                                id,
                                book_id,
                                source,
                                source_url,
                                rating,
                                rating_count,
                                reviews,
                                raw_data,
                                fetched_at
                            )
                        VALUES
                            (
                                gen_random_uuid(),
                                :book_id,
                                :source,
                                :source_url,
                                :rating,
                                :rating_count,
                                CAST(:reviews AS jsonb),
                                CAST(:raw_data AS jsonb),
                                :fetched_at
                            )
                        ON CONFLICT (book_id, source) DO UPDATE SET
                            source_url = EXCLUDED.source_url,
                            rating = EXCLUDED.rating,
                            rating_count = EXCLUDED.rating_count,
                            reviews = EXCLUDED.reviews,
                            raw_data = EXCLUDED.raw_data,
                            fetched_at = EXCLUDED.fetched_at
                    """
                    ),
                    {
                        "book_id": book_id,
                        "source": source.source_name,
                        "source_url": source_url,
                        "rating": fetch_result.rating,
                        "rating_count": fetch_result.rating_count,
                        "reviews": json.dumps(fetch_result.reviews)
                        if fetch_result.reviews
                        else None,
                        "raw_data": json.dumps(fetch_result.raw_data)
                        if fetch_result.raw_data
                        else None,
                        "fetched_at": datetime.now(UTC),
                    },
                )
                await db.commit()
                logger.info(f"Updated {source.source_name} metadata for book {book_id}")
            except Exception as e:
                logger.error(
                    f"Error processing {source.source_name} for book {book_id}: {e}"
                )
                await db.rollback()


async def run_worker() -> None:
    """Main worker loop: blocking pop from Redis queue."""
    logger.info("Metadata worker started")
    client = redis.from_url(settings.redis_url)
    try:
        while True:
            try:
                item = await client.blpop(QUEUE_KEY, timeout=30)
                if item is None:
                    continue
                _, payload_bytes = item
                payload = json.loads(payload_bytes)
                book_id = payload.get("book_id")
                if book_id:
                    logger.info(f"Processing metadata for book {book_id}")
                    await process_job(book_id)
            except Exception as e:
                logger.error(f"Worker error: {e}")
    finally:
        await client.aclose()
