"""Fire-and-forget LLM usage logging."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.llm import TokenUsage

logger = logging.getLogger(__name__)


async def log_llm_usage(
    *,
    feature: str,
    provider: str,
    model: str,
    usage: TokenUsage,
    user_id: uuid.UUID | None = None,
    book_id: uuid.UUID | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Log LLM token usage to the database.

    Uses its own DB session (fire-and-forget) so that usage is always recorded
    even if the caller's transaction rolls back. Failures are logged but never raised.

    Pass session_factory from create_task_engine() when calling from Celery tasks.
    Defaults to AsyncSessionLocal for FastAPI request context.
    """
    try:
        from app.models.llm_usage import LLMUsageLog

        if session_factory is None:
            from app.database import AsyncSessionLocal

            session_factory = AsyncSessionLocal

        async with session_factory() as db:
            db.add(
                LLMUsageLog(
                    user_id=user_id,
                    book_id=book_id,
                    feature=feature,
                    provider=provider,
                    model=model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                )
            )
            await db.commit()
    except Exception:
        logger.warning("Failed to log LLM usage", exc_info=True)
