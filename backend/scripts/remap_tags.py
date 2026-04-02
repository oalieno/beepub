"""One-off script: re-run deterministic tag mapping for all books with external metadata.

Usage: docker compose exec backend python scripts/remap_tags.py
"""

import asyncio
import logging
import uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    from sqlalchemy import text

    from app.database import create_task_engine
    from app.services.tag_mapping import generate_tags_from_metadata

    async with create_task_engine() as (_engine, session_factory):
        # Get all book IDs with external metadata
        async with session_factory() as db:
            result = await db.execute(
                text("SELECT DISTINCT book_id FROM external_metadata")
            )
            book_ids = [str(row[0]) for row in result.fetchall()]

        total = len(book_ids)
        logger.info("Re-mapping tags for %d books...", total)

        success = 0
        errors = 0
        for i, book_id in enumerate(book_ids):
            try:
                async with session_factory() as db:
                    count = await generate_tags_from_metadata(db, uuid.UUID(book_id))
                    await db.commit()
                    if count:
                        success += 1
            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.error("Error for book %s: %s", book_id, e)

            if (i + 1) % 1000 == 0:
                logger.info(
                    "Progress: %d/%d (mapped: %d, errors: %d)",
                    i + 1, total, success, errors,
                )

        logger.info(
            "Done. %d/%d books mapped, %d errors.", success, total, errors
        )


if __name__ == "__main__":
    asyncio.run(main())
