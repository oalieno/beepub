"""Job queue service — run_id tracking, progress counters, and missing book counts."""

from __future__ import annotations

import logging
import time
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
PROGRESS_KEY_PREFIX = "beepub:job:progress"

STOPPED_SENTINEL = "stopped"
COMPLETED_SENTINEL = "completed"
_TERMINAL_VALUES = {STOPPED_SENTINEL, COMPLETED_SENTINEL}


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
}


def _run_id_key(job_type: str) -> str:
    return f"{RUN_ID_KEY_PREFIX}:{job_type}"


def _progress_key(run_id: str) -> str:
    return f"{PROGRESS_KEY_PREFIX}:{run_id}"


async def _get_redis() -> aioredis.Redis:
    """Create a Redis client. Caller must call aclose() when done."""
    return aioredis.from_url(settings.redis_url)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_job_run(job_type: str) -> str:
    """Generate a new run_id for a job and store it in Redis. Returns the run_id."""
    run_id = str(uuid.uuid4())
    client = await _get_redis()
    try:
        # Cleanup old progress hash if a previous run exists
        old = await client.get(_run_id_key(job_type))
        if old:
            old_value = old.decode()
            if old_value not in _TERMINAL_VALUES:
                await client.delete(_progress_key(old_value))
        await client.set(_run_id_key(job_type), run_id)
    finally:
        await client.aclose()
    return run_id


async def stop_job_run(job_type: str) -> bool:
    """Mark a job as stopped. Returns True if there was an active run."""
    client = await _get_redis()
    try:
        current = await client.get(_run_id_key(job_type))
        if not current:
            return False
        value = current.decode()
        if value in _TERMINAL_VALUES:
            return False
        run_id = value
        pipe = client.pipeline()
        pipe.set(_run_id_key(job_type), STOPPED_SENTINEL)
        pipe.hset(_progress_key(run_id), "status", "stopped")
        await pipe.execute()
        return True
    finally:
        await client.aclose()


async def get_active_run_id(job_type: str) -> str | None:
    """Get the current active run_id, or None if no run is active."""
    client = await _get_redis()
    try:
        data = await client.get(_run_id_key(job_type))
        if not data:
            return None
        value = data.decode()
        return None if value in _TERMINAL_VALUES else value
    finally:
        await client.aclose()


async def is_run_active(job_type: str, run_id: str) -> bool:
    """Check if the given run_id is still the active run.

    Returns True only if the key exists and matches this run_id.
    Returns False if key is missing, stopped, completed, or a different run_id.
    """
    client = await _get_redis()
    try:
        data = await client.get(_run_id_key(job_type))
        if not data:
            return False
        value = data.decode()
        if value in _TERMINAL_VALUES:
            return False
        return value == run_id
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------


async def init_job_progress(job_type: str, run_id: str, total: int) -> None:
    """Create a progress hash for a new run. Called by the bulk job orchestrator."""
    client = await _get_redis()
    try:
        await client.hset(
            _progress_key(run_id),
            mapping={
                "total": total,
                "completed": 0,
                "failed": 0,
                "status": "running",
                "last_activity": int(time.time()),
            },
        )
    finally:
        await client.aclose()


async def record_task_completion(run_id: str, job_type: str, *, success: bool) -> None:
    """Increment completed or failed counter and auto-complete if all tasks are done."""
    client = await _get_redis()
    try:
        key = _progress_key(run_id)
        field = "completed" if success else "failed"
        pipe = client.pipeline()
        pipe.hincrby(key, field, 1)
        pipe.hset(key, "last_activity", int(time.time()))
        pipe.hgetall(key)
        results = await pipe.execute()

        progress = results[2]
        if not progress:
            return

        total = int(progress.get(b"total", 0))
        completed = int(progress.get(b"completed", 0))
        failed = int(progress.get(b"failed", 0))

        if total > 0 and completed + failed >= total:
            auto_pipe = client.pipeline()
            auto_pipe.hset(key, "status", "completed")
            auto_pipe.set(_run_id_key(job_type), COMPLETED_SENTINEL)
            await auto_pipe.execute()
            logger.info(
                "Job %s run %s auto-completed: %d/%d (%d failed)",
                job_type,
                run_id,
                completed,
                total,
                failed,
            )
    finally:
        await client.aclose()


@dataclass
class JobProgress:
    total: int
    completed: int
    failed: int
    status: str
    last_activity: float | None


async def get_job_progress(run_id: str) -> JobProgress | None:
    """Read progress hash for a run. Returns None if no progress data exists."""
    client = await _get_redis()
    try:
        data = await client.hgetall(_progress_key(run_id))
        if not data:
            return None
        return JobProgress(
            total=int(data.get(b"total", 0)),
            completed=int(data.get(b"completed", 0)),
            failed=int(data.get(b"failed", 0)),
            status=data.get(b"status", b"running").decode(),
            last_activity=float(data[b"last_activity"])
            if b"last_activity" in data
            else None,
        )
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Missing book counts (for display when no active run)
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
        # Books not yet classified (is_image_book IS NULL) — either no chunks or unclassified
        # Excludes books already classified (even image books with 0 chunks)
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.is_image_book.is_(None))
        )
    elif job_type == "embedding":
        # Missing: non-image books with text but no embeddings
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
        # Blocked: non-image books without text
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(
                Book.id.notin_(has_text), Book.is_image_book.isnot(True)
            )
        )
        blocked = blocked_result.scalar() or 0
    elif job_type == "summarize":
        # Missing: non-image books with text chunks that have unsummarized content
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
        # Blocked: non-image books without text
        blocked_result = await db.execute(
            select(func.count(Book.id)).where(
                Book.id.notin_(has_text), Book.is_image_book.isnot(True)
            )
        )
        blocked = blocked_result.scalar() or 0
    elif job_type == "auto_tag":
        # Books without any AI tags (uses metadata, not text chunks)
        has_tags = select(AiBookTag.book_id).group_by(AiBookTag.book_id)
        missing_result = await db.execute(
            select(func.count(Book.id)).where(Book.id.notin_(has_tags))
        )
    elif job_type == "book_embedding":
        # Non-image books with ALL chunks summarized but no book-level embedding
        from app.models.book_embedding_unified import BookEmbedding

        # Books where every chunk has a summary (no unsummarized chunks remain)
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
        # Blocked: non-image books not fully summarized (no text OR partial summaries)
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
