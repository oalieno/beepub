"""Bridge kosync percentages into BeePub's own reading progress.

Shared by the kosync router (live pushes) and the digest backfill task
(retro-bridging records that arrived before their book had a digest).
Percentage only (BeePub stores 0–100): the CFI and section fields are
left untouched, so the web reader still restores at its last own position.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading import UserBookInteraction


async def bridge_kosync_percentage(
    db: AsyncSession, user_id: uuid.UUID, book_id: uuid.UUID, percentage: float
) -> None:
    """Upsert the interaction's progress percentage (kosync scale 0–1)."""
    interaction = (
        await db.execute(
            select(UserBookInteraction).where(
                UserBookInteraction.user_id == user_id,
                UserBookInteraction.book_id == book_id,
            )
        )
    ).scalar_one_or_none()
    if interaction is None:
        interaction = UserBookInteraction(user_id=user_id, book_id=book_id)
        db.add(interaction)

    reading_progress = dict(interaction.reading_progress or {})
    reading_progress["percentage"] = round(percentage * 100, 2)
    reading_progress["last_read_at"] = datetime.now(UTC).isoformat()
    interaction.reading_progress = reading_progress
