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


async def get_pending_counts(job_types: list[str]) -> dict[str, int]:
    """Get pending counts for many job types over a single Redis connection."""
    async with _redis() as client:
        values = await client.mget([_pending_key(k) for k in job_types])
    return {
        key: max(int(val), 0) if val else 0
        for key, val in zip(job_types, values, strict=True)
    }


async def reset_pending(job_type: str) -> None:
    """Reset the pending counter to 0 (called on stop)."""
    async with _redis() as client:
        await client.delete(_pending_key(job_type))


# ---------------------------------------------------------------------------
# Missing book queries (shared by count + list endpoints)
# ---------------------------------------------------------------------------


def _missing_filters(job_type: str):
    """Return (missing_where, blocked_where) filter clauses for a job type.

    Each is a list of SQLAlchemy WHERE conditions to apply on Book columns.
    blocked_where is None if the job type has no "blocked" concept.
    """
    not_image = Book.is_image_book.isnot(True)

    if job_type == "text_extraction":
        return [Book.is_image_book.is_(None)], None

    elif job_type == "embedding":
        return (
            [Book.has_text.is_(True), Book.has_embedding.is_(False), not_image],
            [Book.has_text.is_(False), not_image],
        )

    elif job_type == "summarize":
        return (
            [Book.has_text.is_(True), Book.is_summarized.is_(False), not_image],
            [Book.has_text.is_(False), not_image],
        )

    elif job_type == "book_embedding":
        return (
            [Book.is_summarized.is_(True), Book.has_embedding.is_(False), not_image],
            [Book.is_summarized.is_(False), not_image],
        )

    elif job_type == "auto_tag":
        return [Book.has_tags.is_(False)], None

    elif job_type == "metadata_backfill":
        return [Book.metadata_count < NUM_METADATA_SOURCES], None

    return None, None


@dataclass
class JobQueueStats:
    total: int
    image_book_count: int
    # job type key -> (missing, blocked)
    counts: dict[str, tuple[int, int]]


async def count_all_job_stats(db: AsyncSession) -> JobQueueStats:
    """Compute every job type's missing/blocked counts in ONE table pass.

    Uses Postgres conditional aggregation (count FILTER (WHERE ...)) so the
    jobs status endpoint issues a single query instead of ~11 sequential
    count(*) scans over books.
    """
    from sqlalchemy import and_

    columns = [
        func.count(Book.id).label("total"),
        func.count(Book.id).filter(Book.is_image_book.is_(True)).label("image"),
    ]
    blocked_keys = set()
    for key in JOB_TYPES:
        missing_where, blocked_where = _missing_filters(key)
        columns.append(
            func.count(Book.id).filter(and_(*missing_where)).label(f"m_{key}")
        )
        if blocked_where is not None:
            blocked_keys.add(key)
            columns.append(
                func.count(Book.id).filter(and_(*blocked_where)).label(f"b_{key}")
            )

    row = (await db.execute(select(*columns))).one()

    counts = {
        key: (
            getattr(row, f"m_{key}") or 0,
            (getattr(row, f"b_{key}") or 0) if key in blocked_keys else 0,
        )
        for key in JOB_TYPES
    }
    return JobQueueStats(
        total=row.total or 0, image_book_count=row.image or 0, counts=counts
    )


async def count_missing_books(db: AsyncSession, job_type: str) -> tuple[int, int]:
    """Return (missing_count, blocked_count) for a job type.

    'missing' = books ready to process (prerequisites met but not yet done).
    'blocked' = books that need a prerequisite first (e.g. text extraction).
    """
    missing_where, blocked_where = _missing_filters(job_type)
    if missing_where is None:
        return 0, 0

    missing_result = await db.execute(select(func.count(Book.id)).where(*missing_where))
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
        no_text_result = await db.execute(
            select(Book.id)
            .where(Book.has_text.is_(False), Book.is_image_book.isnot(True))
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
