"""Job queue service — generation-based run/stop, active counters, and missing book counts."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.book import Book
from app.models.book_embedding_unified import BookEmbedding
from app.models.book_text import BookTextChunk
from app.models.tag import BookTag

logger = logging.getLogger(__name__)

GEN_KEY_PREFIX = "beepub:job:gen"
PENDING_KEY_PREFIX = "beepub:job:pending"

# Number of external metadata sources. Used to determine when a book has been
# fully fetched (all sources attempted). Must match init_metadata_sources().
NUM_METADATA_SOURCES = 4


@dataclass
class JobType:
    key: str
    label: str
    description: str
    requires_ai: bool = False


JOB_TYPES: dict[str, JobType] = {
    "text_extraction": JobType(
        key="text_extraction",
        label="Text Extraction",
        description="Extract text content from EPUB files for search and AI features",
    ),
    "embedding": JobType(
        key="embedding",
        label="Embedding",
        description="Generate vector embeddings for semantic search",
        requires_ai=True,
    ),
    "summarize": JobType(
        key="summarize",
        label="Summarize",
        description="Generate AI summaries for book chapters",
        requires_ai=True,
    ),
    "auto_tag": JobType(
        key="auto_tag",
        label="Auto Tag",
        description="Generate AI tags for books based on content and metadata",
        requires_ai=True,
    ),
    "book_embedding": JobType(
        key="book_embedding",
        label="Book Embedding",
        description="Generate book-level embeddings from chapter summaries",
        requires_ai=True,
    ),
    "metadata_backfill": JobType(
        key="metadata_backfill",
        label="Metadata & Tags",
        description="Fetch external metadata and generate tags (no AI)",
    ),
}


def _gen_key(job_type: str) -> str:
    return f"{GEN_KEY_PREFIX}:{job_type}"


def _pending_key(job_type: str) -> str:
    return f"{PENDING_KEY_PREFIX}:{job_type}"


@asynccontextmanager
async def _redis():
    """Async context manager for a short-lived Redis client."""
    client = aioredis.from_url(settings.redis_url)
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_job(job_type: str) -> int:
    """Start a new run by incrementing the generation counter. Returns the new generation."""
    async with _redis() as client:
        return await client.incr(_gen_key(job_type))


async def stop_job(job_type: str) -> int:
    """Stop a run by incrementing the generation counter and resetting pending.

    In-flight tasks with the old generation will finish, but pending tasks
    will see a different generation and skip.
    Returns the new generation.
    """
    async with _redis() as client:
        gen = await client.incr(_gen_key(job_type))
        await client.delete(_pending_key(job_type))
        return gen


async def get_generation(job_type: str) -> int:
    """Get the current generation counter. Returns 0 if no job has ever run."""
    async with _redis() as client:
        data = await client.get(_gen_key(job_type))
        return int(data) if data else 0


async def is_current_generation(job_type: str, generation: int) -> bool:
    """Check if the given generation is still the current one."""
    return await get_generation(job_type) == generation


# ---------------------------------------------------------------------------
# Active task counter
# ---------------------------------------------------------------------------


async def incr_pending(job_type: str, count: int = 1) -> int:
    """Increment the pending counter (called on dispatch). Returns the new count."""
    async with _redis() as client:
        return await client.incrby(_pending_key(job_type), count)


async def decr_pending(job_type: str) -> int:
    """Decrement the pending counter (called on task completion). Returns the new count (min 0)."""
    async with _redis() as client:
        val = await client.decr(_pending_key(job_type))
        if val < 0:
            await client.set(_pending_key(job_type), 0)
            return 0
        return val


async def get_pending_count(job_type: str) -> int:
    """Get the number of pending tasks (queued + active) for a job type."""
    async with _redis() as client:
        data = await client.get(_pending_key(job_type))
        return max(int(data), 0) if data else 0


async def reset_pending(job_type: str) -> None:
    """Reset the pending counter to 0 (called on stop)."""
    async with _redis() as client:
        await client.delete(_pending_key(job_type))


# ---------------------------------------------------------------------------
# Missing book queries (shared by count + list endpoints)
# ---------------------------------------------------------------------------


def _missing_filters(job_type: str):
    """Return (missing_where, blocked_where) filter clauses for a job type.

    Each is a list of SQLAlchemy WHERE conditions to apply on Book.id.
    blocked_where is None if the job type has no "blocked" concept.
    """
    from app.models.book import ExternalMetadata

    has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)

    if job_type == "text_extraction":
        return [Book.is_image_book.is_(None)], None

    elif job_type == "embedding":
        has_embed = select(BookEmbedding.book_id)
        missing = [
            Book.id.in_(has_text),
            Book.id.notin_(has_embed),
            Book.is_image_book.isnot(True),
        ]
        blocked = [Book.id.notin_(has_text), Book.is_image_book.isnot(True)]
        return missing, blocked

    elif job_type == "summarize":
        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        missing = [
            Book.id.in_(has_unsummarized),
            Book.is_image_book.isnot(True),
        ]
        blocked = [Book.id.notin_(has_text), Book.is_image_book.isnot(True)]
        return missing, blocked

    elif job_type == "auto_tag":
        has_tags = select(BookTag.book_id).group_by(BookTag.book_id)
        return [Book.id.notin_(has_tags)], None

    elif job_type == "metadata_backfill":
        fully_fetched = (
            select(ExternalMetadata.book_id)
            .group_by(ExternalMetadata.book_id)
            .having(func.count(ExternalMetadata.source) >= NUM_METADATA_SOURCES)
        )
        return [Book.id.notin_(fully_fetched)], None

    elif job_type == "book_embedding":
        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        fully_summarized = (
            select(BookTextChunk.book_id)
            .group_by(BookTextChunk.book_id)
            .except_(has_unsummarized)
        )
        has_book_embed = select(BookEmbedding.book_id)
        missing = [
            Book.id.in_(fully_summarized),
            Book.id.notin_(has_book_embed),
            Book.is_image_book.isnot(True),
        ]
        blocked = [
            Book.id.notin_(fully_summarized),
            Book.is_image_book.isnot(True),
        ]
        return missing, blocked

    return None, None


async def count_missing_books(db: AsyncSession, job_type: str) -> tuple[int, int]:
    """Return (missing_count, blocked_count) for a job type.

    'missing' = books ready to process (prerequisites met but not yet done).
    'blocked' = books that need a prerequisite first (e.g. text extraction).
    """
    missing_where, blocked_where = _missing_filters(job_type)
    if missing_where is None:
        return 0, 0

    missing_result = await db.execute(
        select(func.count(Book.id)).where(*missing_where)
    )
    missing = missing_result.scalar() or 0

    blocked = 0
    if blocked_where is not None:
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(*blocked_where)
        )
        blocked = blocked_result.scalar() or 0

    return missing, blocked


async def get_missing_book_ids(db: AsyncSession, job_type: str) -> list:
    """Return book IDs that need processing for a job type.

    For 'summarize', also includes books without text (they need extraction first).
    """
    missing_where, _ = _missing_filters(job_type)
    if missing_where is None:
        return []

    result = await db.execute(
        select(Book.id).where(*missing_where).order_by(Book.created_at)
    )
    book_ids = [row[0] for row in result.all()]

    # Summarize also needs books without text (extraction runs first)
    if job_type == "summarize":
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        no_text_result = await db.execute(
            select(Book.id)
            .where(Book.id.notin_(has_text), Book.is_image_book.isnot(True))
            .order_by(Book.created_at)
        )
        no_text_ids = [row[0] for row in no_text_result.all()]
        # Merge: no_text first, then unsummarized (deduped)
        seen = set(book_ids)
        for bid in no_text_ids:
            if bid not in seen:
                seen.add(bid)
                book_ids.append(bid)

    return book_ids
