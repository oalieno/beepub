"""Shared helpers for metadata fetching (used by both per-book and backfill tasks)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.services.metadata_sources.base import AbstractMetadataSource, FetchResult

logger = logging.getLogger(__name__)


async def init_metadata_sources(
    session_factory: async_sessionmaker,
) -> list[AbstractMetadataSource]:
    """Load API keys from settings and create all source instances."""
    from app.services.metadata_sources import (
        GoodreadsSource,
        GoogleBooksSource,
        HardcoverSource,
        ReadmooSource,
    )
    from app.services.settings import get_all_settings as _get_settings

    async with session_factory() as settings_db:
        app_settings = await _get_settings(settings_db)

    google_api_key = app_settings.get("google_books_api_key", "")
    hardcover_token = app_settings.get("hardcover_api_token", "")

    return [
        GoodreadsSource(),
        ReadmooSource(),
        GoogleBooksSource(api_key=google_api_key),
        HardcoverSource(api_token=hardcover_token),
    ]


async def fetch_book_info(
    db: AsyncSession, book_id: str
) -> tuple[str, list[str], str | None] | None:
    """Return (title, authors, isbn) for a book, or None if not found / no title."""
    result = await db.execute(
        text(
            "SELECT id, epub_title, epub_authors, epub_isbn, title, authors "
            "FROM books WHERE id = :id"
        ),
        {"id": book_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        return None

    display_title = row["title"] or row["epub_title"] or ""
    display_authors = row["authors"] or row["epub_authors"] or []
    isbn = row["epub_isbn"]

    if not display_title:
        return None

    return display_title, display_authors, isbn


async def upsert_external_metadata(
    db: AsyncSession,
    book_id: str,
    source_name: str,
    source_url: str,
    fetch_result: FetchResult,
) -> None:
    """INSERT ... ON CONFLICT DO UPDATE for external_metadata."""
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
            "source": source_name,
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


async def search_and_fetch(
    source: AbstractMetadataSource,
    title: str,
    authors: list[str],
    isbn: str | None,
    book_id: str,
) -> tuple[FetchResult, str] | None:
    """Search a source and fetch the best result. Returns (fetch_result, source_url) or None."""
    results = await source.search(title, authors, isbn)
    if not results:
        logger.info(f"No results from {source.source_name} for book {book_id}")
        return None

    best = results[0]
    if best.score < 60:
        logger.debug(
            f"Skipping {source.source_name} for book {book_id}: low score {best.score:.0f}"
        )
        return None

    if best.prefetched:
        fetch_result = best.prefetched
    else:
        fetch_result = await source.fetch(best.url)

    return fetch_result, fetch_result.source_url


async def run_tag_mapping(session_factory: async_sessionmaker, book_id: str) -> None:
    """Run deterministic tag mapping for a book."""
    from app.services.tag_mapping import generate_tags_from_metadata

    try:
        async with session_factory() as db:
            count = await generate_tags_from_metadata(db, uuid.UUID(book_id))
            await db.commit()
            if count:
                logger.info(f"Mapped {count} external tags for book {book_id}")
    except Exception as e:
        logger.error(f"Error mapping tags for book {book_id}: {e}")
