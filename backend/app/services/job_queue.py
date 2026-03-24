"""Job queue service — run_id tracking and missing book counts for admin jobs."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.book import Book
from app.models.book_embedding import BookEmbeddingChunk
from app.models.book_text import BookTextChunk
from app.models.tag import AiBookTag

logger = logging.getLogger(__name__)

RUN_ID_KEY_PREFIX = "beepub:job:run_id"
RUN_ID_TTL_SECONDS = 86400  # 24 hours


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
    "word_count": JobType(
        key="word_count",
        label="Word Count",
        description="Compute word counts for books",
    ),
}


def _run_id_key(job_type: str) -> str:
    return f"{RUN_ID_KEY_PREFIX}:{job_type}"


async def start_job_run(job_type: str) -> str:
    """Generate a new run_id for a job and store it in Redis. Returns the run_id."""
    run_id = str(uuid.uuid4())
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.set(_run_id_key(job_type), run_id, ex=RUN_ID_TTL_SECONDS)
    finally:
        await client.aclose()
    return run_id


STOPPED_SENTINEL = "stopped"


async def stop_job_run(job_type: str) -> bool:
    """Mark a job as stopped. Returns True if there was an active run."""
    client = aioredis.from_url(settings.redis_url)
    try:
        current = await client.get(_run_id_key(job_type))
        if not current or current.decode() == STOPPED_SENTINEL:
            return False
        await client.set(_run_id_key(job_type), STOPPED_SENTINEL, ex=RUN_ID_TTL_SECONDS)
        return True
    finally:
        await client.aclose()


async def get_active_run_id(job_type: str) -> str | None:
    """Get the current active run_id, or None if no run is active."""
    client = aioredis.from_url(settings.redis_url)
    try:
        data = await client.get(_run_id_key(job_type))
        if not data:
            return None
        value = data.decode()
        return None if value == STOPPED_SENTINEL else value
    finally:
        await client.aclose()


async def is_run_active(job_type: str, run_id: str) -> bool:
    """Check if the given run_id is still the active run.

    Returns True only if the key exists and matches this run_id.
    Returns False if key is missing (expired), stopped, or a different run_id.
    """
    client = aioredis.from_url(settings.redis_url)
    try:
        data = await client.get(_run_id_key(job_type))
        if not data:
            return False
        value = data.decode()
        if value == STOPPED_SENTINEL:
            return False
        return value == run_id
    finally:
        await client.aclose()


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
        # Books without any BookTextChunk rows
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_text))
        )
    elif job_type == "embedding":
        # Missing: books with text but no embeddings
        has_embed = select(BookEmbeddingChunk.book_id).group_by(
            BookEmbeddingChunk.book_id
        )
        missing_result = await db.execute(
            select(func.count()).select_from(has_text.except_(has_embed).subquery())
        )
        # Blocked: books without text (need text extraction first)
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_text))
        )
        blocked = blocked_result.scalar() or 0
    elif job_type == "summarize":
        # Missing: books with text chunks that have unsummarized content
        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        missing_result = await db.execute(
            select(func.count()).select_from(has_unsummarized.subquery())
        )
        # Blocked: books without text (need text extraction first)
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_text))
        )
        blocked = blocked_result.scalar() or 0
    elif job_type == "auto_tag":
        # Books without any AI tags (uses metadata, not text chunks)
        has_tags = select(AiBookTag.book_id).group_by(AiBookTag.book_id)
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_tags))
        )
    elif job_type == "word_count":
        # Books where word_count is NULL (reads EPUB file directly)
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.word_count.is_(None))
        )
    else:
        return total, 0, 0

    missing = missing_result.scalar() or 0
    return total, missing, blocked
