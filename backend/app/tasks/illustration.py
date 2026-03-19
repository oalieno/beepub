"""Celery task for generating illustrations via Gemini API."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
import zipfile

from app.celeryapp import celery

logger = logging.getLogger(__name__)

# Errors that won't resolve with retries
NO_RETRY_MARKERS = ["IMAGE_SAFETY", "SAFETY", "BLOCKED"]


def _load_reference_images(reference_images: list[dict] | None) -> list[bytes] | None:
    """Read reference image bytes from epub or illustration files."""
    if not reference_images:
        return None
    result = []
    for ref in reference_images:
        if ref["type"] == "epub":
            with zipfile.ZipFile(ref["epub_path"], "r") as zf:
                result.append(zf.read(ref["image_path"]))
        elif ref["type"] == "illustration":
            with open(ref["file_path"], "rb") as f:
                result.append(f.read())
    return result or None


async def _run(
    illustration_id: str,
    text: str,
    style_prompt: str | None,
    custom_prompt: str | None,
    image_path: str,
    reference_images: list[dict] | None,
) -> None:
    from app.services.gemini import generate_illustration

    ref_bytes = _load_reference_images(reference_images)
    image_bytes = await generate_illustration(
        text, style_prompt, custom_prompt, reference_images=ref_bytes
    )
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    with open(image_path, "wb") as f:
        f.write(image_bytes)
    logger.info("Illustration %s image saved", illustration_id)


async def _mark_status(
    illustration_id: str, status: str, error_message: str | None = None
) -> None:
    from sqlalchemy import select

    from app.database import create_task_session
    from app.models.illustration import Illustration

    SessionLocal = create_task_session()
    async with SessionLocal() as db:
        result = await db.execute(
            select(Illustration).where(
                Illustration.id == uuid.UUID(illustration_id)
            )
        )
        ill = result.scalar_one()
        ill.status = status
        if error_message is not None:
            ill.error_message = error_message[:500]
        await db.commit()


def _safe_mark(illustration_id: str, status: str, error_message: str | None = None) -> None:
    """Mark illustration status, logging any DB errors instead of raising."""
    try:
        asyncio.run(_mark_status(illustration_id, status, error_message))
    except Exception:
        logger.exception(
            "Failed to mark illustration %s as %s", illustration_id, status
        )


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
    reference_images: list[dict] | None = None,
) -> None:
    """Celery task: call Gemini API to generate an illustration."""
    try:
        asyncio.run(
            _run(
                illustration_id, text, style_prompt, custom_prompt,
                image_path, reference_images,
            )
        )
        # Success — mark completed
        _safe_mark(illustration_id, "completed")
        logger.info("Illustration %s completed", illustration_id)
    except Exception as exc:
        exc_msg = str(exc)

        # Non-retryable errors — mark failed immediately
        if any(marker in exc_msg for marker in NO_RETRY_MARKERS):
            logger.warning(
                "generate_illustration_task permanently failed for %s: %s",
                illustration_id,
                exc_msg,
            )
            _safe_mark(illustration_id, "failed", exc_msg)
            return

        # Retryable — only mark failed if no retries left
        retries_left = self.max_retries - self.request.retries
        if retries_left <= 0:
            logger.error(
                "generate_illustration_task exhausted retries for %s: %s",
                illustration_id,
                exc_msg,
            )
            _safe_mark(illustration_id, "failed", exc_msg)
            return

        logger.warning(
            "generate_illustration_task retrying for %s (attempt %d/%d): %s",
            illustration_id,
            self.request.retries + 1,
            self.max_retries + 1,
            exc_msg,
        )
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
