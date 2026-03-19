"""Celery task for generating illustrations via Gemini API."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)


async def _run(
    illustration_id: str,
    text: str,
    style_prompt: str | None,
    custom_prompt: str | None,
    image_path: str,
) -> None:
    from sqlalchemy import select

    from app.database import create_task_session
    from app.models.illustration import Illustration
    from app.services.gemini import generate_illustration

    SessionLocal = create_task_session()
    async with SessionLocal() as db:
        try:
            image_bytes = await generate_illustration(text, style_prompt, custom_prompt)
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            with open(image_path, "wb") as f:
                f.write(image_bytes)
            result = await db.execute(
                select(Illustration).where(
                    Illustration.id == uuid.UUID(illustration_id)
                )
            )
            ill = result.scalar_one()
            ill.status = "completed"
            await db.commit()
            logger.info("Illustration %s completed", illustration_id)
        except Exception as e:
            logger.exception(
                "Illustration generation failed for %s", illustration_id
            )
            result = await db.execute(
                select(Illustration).where(
                    Illustration.id == uuid.UUID(illustration_id)
                )
            )
            ill = result.scalar_one()
            ill.status = "failed"
            ill.error_message = (str(e) or repr(e))[:500]
            await db.commit()
            raise


@celery.task(
    name="app.tasks.illustration.generate_illustration_task",
    bind=True,
    max_retries=2,
)
def generate_illustration_task(
    self,
    illustration_id: str,
    text: str,
    style_prompt: str | None,
    custom_prompt: str | None,
    image_path: str,
) -> None:
    """Celery task: call Gemini API to generate an illustration."""
    try:
        asyncio.run(
            _run(illustration_id, text, style_prompt, custom_prompt, image_path)
        )
    except Exception as exc:
        logger.exception(
            "generate_illustration_task failed for %s (attempt %d/%d)",
            illustration_id,
            self.request.retries + 1,
            self.max_retries + 1,
        )
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
