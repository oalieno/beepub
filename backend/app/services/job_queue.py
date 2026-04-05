"""Job queue service — generation-based run/stop, active counters, and missing book counts."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.book import Book
from app.models.book_embedding import BookEmbeddingChunk
from app.models.book_text import BookTextChunk
from app.models.tag import BookTag

logger = logging.getLogger(__name__)

GEN_KEY_PREFIX = "beepub:job:gen"
ACTIVE_KEY_PREFIX = "beepub:job:active"


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


def _active_key(job_type: str) -> str:
    return f"{ACTIVE_KEY_PREFIX}:{job_type}"


async def _get_redis() -> aioredis.Redis:
    """Create a Redis client. Caller must call aclose() when done."""
    return aioredis.from_url(settings.redis_url)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_job(job_type: str) -> int:
    """Start a new run by incrementing the generation counter. Returns the new generation."""
    client = await _get_redis()
    try:
        gen = await client.incr(_gen_key(job_type))
        return gen
    finally:
        await client.aclose()


async def stop_job(job_type: str) -> int:
    """Stop a run by incrementing the generation counter.

    In-flight tasks with the old generation will finish, but pending tasks
    will see a different generation and skip.
    Returns the new generation.
    """
    client = await _get_redis()
    try:
        gen = await client.incr(_gen_key(job_type))
        return gen
    finally:
        await client.aclose()


async def get_generation(job_type: str) -> int:
    """Get the current generation counter. Returns 0 if no job has ever run."""
    client = await _get_redis()
    try:
        data = await client.get(_gen_key(job_type))
        return int(data) if data else 0
    finally:
        await client.aclose()


async def is_current_generation(job_type: str, generation: int) -> bool:
    """Check if the given generation is still the current one."""
    return await get_generation(job_type) == generation


# ---------------------------------------------------------------------------
# Active task counter
# ---------------------------------------------------------------------------


async def incr_active(job_type: str) -> int:
    """Increment the active task counter. Returns the new count."""
    client = await _get_redis()
    try:
        return await client.incr(_active_key(job_type))
    finally:
        await client.aclose()


async def decr_active(job_type: str) -> int:
    """Decrement the active task counter. Returns the new count (min 0)."""
    client = await _get_redis()
    try:
        val = await client.decr(_active_key(job_type))
        if val < 0:
            await client.set(_active_key(job_type), 0)
            return 0
        return val
    finally:
        await client.aclose()


async def get_active_count(job_type: str) -> int:
    """Get the number of currently active tasks for a job type."""
    client = await _get_redis()
    try:
        data = await client.get(_active_key(job_type))
        return max(int(data), 0) if data else 0
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Missing book counts
# ---------------------------------------------------------------------------


async def count_missing_books(db: AsyncSession, job_type: str) -> tuple[int, int, int]:
    """Return (total_books, missing_count, blocked_count) for a job type.

    'missing' = books ready to process (prerequisites met but not yet done).
    'blocked' = books that need a prerequisite first (e.g. text extraction).
    """
    total_result = await db.execute(select(func.count(Book.id)))
    total = total_result.scalar() or 0
    blocked = 0

    has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)

    if job_type == "text_extraction":
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.is_image_book.is_(None))
        )
    elif job_type == "embedding":
        has_embed = select(BookEmbeddingChunk.book_id).group_by(
            BookEmbeddingChunk.book_id
        )
        non_image_text = has_text.where(
            BookTextChunk.book_id.in_(
                select(Book.id).where(Book.is_image_book.isnot(True))
            )
        )
        missing_result = await db.execute(
            select(func.count()).select_from(
                non_image_text.except_(has_embed).subquery()
            )
        )
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(
                Book.id.notin_(has_text), Book.is_image_book.isnot(True)
            )
        )
        blocked = blocked_result.scalar() or 0
    elif job_type == "summarize":
        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        missing_result = await db.execute(
            select(func.count(Book.id)).where(
                Book.id.in_(has_unsummarized), Book.is_image_book.isnot(True)
            )
        )
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(
                Book.id.notin_(has_text), Book.is_image_book.isnot(True)
            )
        )
        blocked = blocked_result.scalar() or 0
    elif job_type == "auto_tag":
        has_tags = select(BookTag.book_id).group_by(BookTag.book_id)
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_tags))
        )
    elif job_type == "metadata_backfill":
        from app.models.book import ExternalMetadata

        fully_fetched = (
            select(ExternalMetadata.book_id)
            .group_by(ExternalMetadata.book_id)
            .having(func.count(ExternalMetadata.source) >= 4)
        )
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(fully_fetched))
        )
    elif job_type == "book_embedding":
        from app.models.book_embedding_unified import BookEmbedding

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
        missing_result = await db.execute(
            select(func.count(Book.id)).where(
                Book.id.in_(fully_summarized),
                Book.id.notin_(has_book_embed),
                Book.is_image_book.isnot(True),
            )
        )
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(
                Book.id.notin_(fully_summarized),
                Book.is_image_book.isnot(True),
            )
        )
        blocked = blocked_result.scalar() or 0
    else:
        return total, 0, 0

    missing = missing_result.scalar() or 0
    return total, missing, blocked
