"""Celery task for AI auto-tagging books via Gemini."""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _process_auto_tag(book_id: str) -> None:
    """Generate AI tags for the given book."""
    from sqlalchemy import text

    from app.database import create_task_session
    from app.services.tags import generate_ai_tags, save_ai_tags

    SessionLocal = create_task_session()

    async with SessionLocal() as db:
        # Get book metadata
        result = await db.execute(
            text(
                "SELECT id, epub_title, epub_authors, epub_description, epub_language, "
                "title, authors, description "
                "FROM books WHERE id = :id"
            ),
            {"id": book_id},
        )
        row = result.mappings().one_or_none()
        if not row:
            logger.warning("Book %s not found, skipping auto-tag", book_id)
            return

        display_title = row["title"] or row["epub_title"]
        if not display_title:
            logger.info("Book %s has no title, skipping auto-tag", book_id)
            return

        display_authors = row["authors"] or row["epub_authors"]
        display_description = row["description"] or row["epub_description"]
        language = row["epub_language"]

        # Get reviews from external metadata
        reviews_result = await db.execute(
            text(
                "SELECT reviews FROM external_metadata "
                "WHERE book_id = :book_id AND reviews IS NOT NULL"
            ),
            {"book_id": book_id},
        )
        reviews = []
        for r in reviews_result.fetchall():
            if r[0]:
                reviews.extend(r[0])

        # Generate tags via LLM
        tags = await generate_ai_tags(
            title=display_title,
            authors=display_authors,
            description=display_description,
            language=language,
            reviews=reviews or None,
        )

        if not tags:
            logger.warning("No valid AI tags generated for book %s", book_id)
            return

        # Save tags
        await save_ai_tags(db, uuid.UUID(book_id), tags)
        await db.commit()
        logger.info(
            "Auto-tagged book %s with %d tags: %s",
            book_id,
            len(tags),
            [t["tag"] for t in tags],
        )


@celery.task(name="app.tasks.auto_tag.auto_tag_book", bind=True, max_retries=2)
def auto_tag_book(self, book_id: str) -> None:
    """Celery task: generate AI tags for a book."""
    try:
        asyncio.run(_process_auto_tag(book_id))
    except Exception as exc:
        logger.exception("auto_tag_book failed for book %s", book_id)
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
