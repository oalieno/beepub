"""Job queue service — Redis-based progress tracking for bulk Celery tasks."""

from __future__ import annotations

import json
import logging
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

JOB_KEY_PREFIX = "beepub:job"

# TTL for progress keys — prevents stuck state if worker crashes
JOB_TTL_SECONDS = 86400  # 24 hours


@dataclass
class JobType:
    key: str
    label: str
    description: str


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
    ),
    "summarize": JobType(
        key="summarize",
        label="Summarize",
        description="Generate AI summaries for book chapters",
    ),
    "auto_tag": JobType(
        key="auto_tag",
        label="Auto Tag",
        description="Generate AI tags for books based on content and metadata",
    ),
    "word_count": JobType(
        key="word_count",
        label="Word Count",
        description="Compute word counts for books",
    ),
    "summary_embedding": JobType(
        key="summary_embedding",
        label="Summary Embedding",
        description="Generate book-level embeddings from chapter summaries for semantic similar books",
    ),
}


def _job_key(job_type: str) -> str:
    return f"{JOB_KEY_PREFIX}:{job_type}"


async def get_job_status(job_type: str) -> dict | None:
    """Get current job status from Redis."""
    client = aioredis.from_url(settings.redis_url)
    try:
        data = await client.get(_job_key(job_type))
        if data:
            return json.loads(data)
        return None
    except Exception:
        logger.warning("Failed to read job status for %s", job_type, exc_info=True)
        return None
    finally:
        await client.aclose()


async def set_job_status(
    job_type: str,
    *,
    status: str,
    total: int = 0,
    processed: int = 0,
    failed: int = 0,
) -> None:
    """Set job status in Redis with TTL."""
    client = aioredis.from_url(settings.redis_url)
    try:
        data = json.dumps(
            {
                "status": status,
                "total": total,
                "processed": processed,
                "failed": failed,
            }
        )
        await client.set(_job_key(job_type), data, ex=JOB_TTL_SECONDS)
    finally:
        await client.aclose()


async def clear_job_status(job_type: str) -> None:
    """Clear job status from Redis."""
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.delete(_job_key(job_type))
    finally:
        await client.aclose()


async def get_all_job_statuses() -> dict[str, dict]:
    """Get status for all job types in a single Redis connection."""
    client = aioredis.from_url(settings.redis_url)
    try:
        result = {}
        for job_type in JOB_TYPES:
            data = await client.get(_job_key(job_type))
            if data:
                result[job_type] = json.loads(data)
            else:
                result[job_type] = None
        return result
    except Exception:
        logger.warning("Failed to read job statuses from Redis", exc_info=True)
        return {job_type: None for job_type in JOB_TYPES}
    finally:
        await client.aclose()


async def count_missing_books(db: AsyncSession, job_type: str) -> tuple[int, int]:
    """Return (total_books, missing_count) for a job type.

    'missing' = books that haven't been processed by this job type yet.
    """
    total_result = await db.execute(select(func.count(Book.id)))
    total = total_result.scalar() or 0

    if job_type == "text_extraction":
        # Books without any BookTextChunk rows
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_text))
        )
    elif job_type == "embedding":
        # Books without embedding chunks (orchestrator handles text extraction as prerequisite)
        has_embed = select(BookEmbeddingChunk.book_id).group_by(
            BookEmbeddingChunk.book_id
        )
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_embed))
        )
    elif job_type == "summarize":
        # Books without any text chunks, plus books with unsummarized text chunks
        has_text = select(BookTextChunk.book_id).group_by(BookTextChunk.book_id)
        has_unsummarized = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.is_(None))
            .group_by(BookTextChunk.book_id)
        )
        # Count books that either have no text at all, or have unsummarized chunks
        no_text_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_text))
        )
        unsummarized_result = await db.execute(
            select(func.count()).select_from(has_unsummarized.subquery())
        )
        missing = (no_text_result.scalar() or 0) + (unsummarized_result.scalar() or 0)
        return total, missing
    elif job_type == "auto_tag":
        # Books without any AI tags
        has_tags = select(AiBookTag.book_id).group_by(AiBookTag.book_id)
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_tags))
        )
    elif job_type == "word_count":
        # Books where word_count is NULL
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.word_count.is_(None))
        )
    elif job_type == "summary_embedding":
        # Books with summaries but no BookSummaryEmbedding
        from app.models.book_summary_embedding import BookSummaryEmbedding

        has_summary = (
            select(BookTextChunk.book_id)
            .where(BookTextChunk.summary.isnot(None))
            .group_by(BookTextChunk.book_id)
        )
        has_embed = select(BookSummaryEmbedding.book_id)
        missing_result = await db.execute(
            select(func.count())
            .select_from(has_summary.except_(has_embed).subquery())
        )
    else:
        return total, 0

    missing = missing_result.scalar() or 0
    return total, missing
