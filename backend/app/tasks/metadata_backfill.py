"""Metadata backfill task: fetch external metadata + deterministic tag mapping.

No AI/LLM calls. Handles rate limits with exponential backoff.
Rate limits:
  - Google Books: 1000 requests/day
  - Hardcover: 60 requests/minute
  - Goodreads/Readmoo: scraping, be polite (~1 req/sec)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Delay between books to respect rate limits (seconds)
# 4 sources × 60k books = 240k requests. At 1.5s/book ≈ 25h total.
DELAY_BETWEEN_BOOKS = 1.5


async def _run_metadata_backfill(book_id: str) -> None:
    """Fetch metadata from all sources for a book, then run deterministic tag mapping.

    Unlike fetch_metadata, this does NOT chain to auto_tag_book (no AI).
    Includes a delay to respect API rate limits.
    """
    from app.database import create_task_engine
    from app.services.metadata_sources import (
        GoodreadsSource,
        GoogleBooksSource,
        HardcoverSource,
        ReadmooSource,
    )
    from app.services.settings import get_all_settings as _get_settings
    from app.services.tag_mapping import generate_tags_from_metadata

    async with create_task_engine() as (_engine, session_factory):
        # Load API keys
        async with session_factory() as settings_db:
            app_settings = await _get_settings(settings_db)

        google_api_key = app_settings.get("google_books_api_key", "")
        hardcover_token = app_settings.get("hardcover_api_token", "")

        sources = [
            GoodreadsSource(),
            ReadmooSource(),
            GoogleBooksSource(api_key=google_api_key),
            HardcoverSource(api_token=hardcover_token),
        ]

        async with session_factory() as db:
            result = await db.execute(
                text(
                    "SELECT id, epub_title, epub_authors, epub_isbn, title, authors "
                    "FROM books WHERE id = :id"
                ),
                {"id": book_id},
            )
            row = result.mappings().one_or_none()
            if not row:
                logger.warning("Book %s not found, skipping", book_id)
                return

            display_title = row["title"] or row["epub_title"] or ""
            display_authors = row["authors"] or row["epub_authors"] or []
            isbn = row["epub_isbn"]

            if not display_title:
                logger.info("Book %s has no title, skipping", book_id)
                return

            for source in sources:
                try:
                    # Check for pinned URL
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
                        fetch_result = await source.fetch(pinned_url)
                        source_url = pinned_url
                    else:
                        results = await source.search(
                            display_title, display_authors, isbn
                        )
                        if not results:
                            continue

                        best = results[0]
                        if best.score < 60:
                            logger.debug(
                                "Skipping %s for book %s: low score %.0f",
                                source.source_name,
                                book_id,
                                best.score,
                            )
                            continue
                        if best.prefetched:
                            fetch_result = best.prefetched
                        else:
                            fetch_result = await source.fetch(best.url)
                        source_url = fetch_result.source_url

                    # Upsert external_metadata
                    await db.execute(
                        text("""
                            INSERT INTO external_metadata
                                (id, book_id, source, source_url, rating,
                                 rating_count, reviews, raw_data, fetched_at)
                            VALUES
                                (gen_random_uuid(), :book_id, :source, :source_url,
                                 :rating, :rating_count, CAST(:reviews AS jsonb),
                                 CAST(:raw_data AS jsonb), :fetched_at)
                            ON CONFLICT (book_id, source) DO UPDATE SET
                                source_url = EXCLUDED.source_url,
                                rating = EXCLUDED.rating,
                                rating_count = EXCLUDED.rating_count,
                                reviews = EXCLUDED.reviews,
                                raw_data = EXCLUDED.raw_data,
                                fetched_at = EXCLUDED.fetched_at
                        """),
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
                except Exception as e:
                    logger.error(
                        "Error fetching %s for book %s: %s",
                        source.source_name,
                        book_id,
                        e,
                    )
                    await db.rollback()

        # Run deterministic tag mapping (no AI)
        try:
            async with session_factory() as db:
                count = await generate_tags_from_metadata(db, uuid.UUID(book_id))
                await db.commit()
                if count:
                    logger.info("Backfill: mapped %d tags for book %s", count, book_id)
        except Exception as e:
            logger.error("Error mapping tags for book %s: %s", book_id, e)

        # Rate limit: pause between books
        await asyncio.sleep(DELAY_BETWEEN_BOOKS)
