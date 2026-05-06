"""One-off: compute and persist books.popularity_score for every book.

Run after the 037 migration. Subsequent updates happen automatically when
metadata is fetched, work_id changes, or series is edited.

Usage: docker compose exec backend python scripts/backfill_popularity.py
"""

import asyncio
import logging
import uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 500


async def main() -> None:
    from sqlalchemy import text

    from app.database import create_task_engine
    from app.services.popularity import recompute_popularity

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            result = await db.execute(text("SELECT id FROM books ORDER BY id"))
            book_ids = [uuid.UUID(str(row[0])) for row in result.fetchall()]

        total = len(book_ids)
        logger.info("Recomputing popularity for %d books...", total)

        for i in range(0, total, BATCH_SIZE):
            batch = book_ids[i : i + BATCH_SIZE]
            async with session_factory() as db:
                await recompute_popularity(db, batch)
                await db.commit()
            logger.info("Progress: %d/%d", min(i + BATCH_SIZE, total), total)

        logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
