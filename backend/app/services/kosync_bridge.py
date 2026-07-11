"""Bridge kosync percentages into BeePub's own reading progress.

Shared by the kosync router (live pushes) and the digest bulk job
(retro-bridging records that arrived before their book had a digest).
Percentage only (BeePub stores 0–100): the CFI and section fields are
left untouched, so the web reader still restores at its last own position —
but a ``kosync`` marker is added so the reader can offer jumping to the
device position.
"""

import re
import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading import UserBookInteraction

_DOCFRAGMENT_RE = re.compile(r"/DocFragment\[(\d+)\]")


def section_hint_from_xpointer(progress: str | None) -> int | None:
    """0-based spine index from a crengine xpointer, if one is encoded.

    KOReader EPUB positions look like ``/body/DocFragment[7]/body/p[3]/...``
    where DocFragment[N] is the 1-based spine item. Page-number strings
    (PDF) and anything else yield None. The full path is a cross-renderer
    mapping minefield; the fragment index alone is a safe chapter hint.
    """
    if not progress:
        return None
    match = _DOCFRAGMENT_RE.search(progress)
    if not match:
        return None
    n = int(match.group(1))
    return n - 1 if n >= 1 else None


async def _today_in_app_timezone(db: AsyncSession) -> date:
    from app.services.settings import get_setting

    tz_name = await get_setting(db, "timezone")
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.now(UTC).date()


async def bridge_kosync_percentage(
    db: AsyncSession,
    user_id: uuid.UUID,
    book_id: uuid.UUID,
    percentage: float,
    device: str | None = None,
    section_index: int | None = None,
    xpointer: str | None = None,
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

    now = datetime.now(UTC).isoformat()
    reading_progress = dict(interaction.reading_progress or {})
    reading_progress["percentage"] = round(percentage * 100, 2)
    reading_progress["last_read_at"] = now
    # Marker for the web reader: "an e-reader moved past the stored CFI".
    # The web PUT /progress rebuilds the dict from scratch, so the marker
    # lives exactly until the user reads on the web again — its presence
    # alone means the device position is newer, no timestamp comparison.
    reading_progress["kosync"] = {
        "percentage": reading_progress["percentage"],
        "device": device,
        "synced_at": now,
        # Chapter hint parsed from the device xpointer: lets the web jump
        # land on the right section even when percentage scales diverge
        # between renderers (image-heavy books).
        "section_index": section_index,
        # The raw device xpointer, kept only when it parsed as an EPUB path
        # (section_index found): the web reader walks it through the section
        # DOM for a paragraph-level jump, degrading to the chapter hint.
        "xpointer": xpointer if section_index is not None else None,
    }
    interaction.reading_progress = reading_progress

    # Mirror the web reader's auto-mark behaviour: reading on an e-reader
    # means the book is being read. Only upgrade from empty/want_to_read —
    # never demote read / did_not_finish, and keep an existing started_at.
    if interaction.reading_status in (None, "want_to_read"):
        interaction.reading_status = "currently_reading"
        if interaction.started_at is None:
            interaction.started_at = await _today_in_app_timezone(db)


async def retro_bridge_document(
    db: AsyncSession, book_id: uuid.UUID, digest: str
) -> int:
    """Apply stored kosync records whose document just gained a book.

    Mirrors the router's access rule by skipping users excluded from the
    book's library. Returns the number of records applied.
    """
    from app.models.kosync import KosyncProgress
    from app.models.library import Library, LibraryBook, UserLibraryExclusion

    records = (
        (
            await db.execute(
                select(KosyncProgress).where(
                    KosyncProgress.document == digest,
                    KosyncProgress.percentage.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    bridged = 0
    for record in records:
        excluded = (
            await db.execute(
                select(UserLibraryExclusion.library_id)
                .join(Library, Library.id == UserLibraryExclusion.library_id)
                .join(LibraryBook, LibraryBook.library_id == Library.id)
                .where(
                    UserLibraryExclusion.user_id == record.user_id,
                    LibraryBook.book_id == book_id,
                )
            )
        ).first()
        if excluded:
            continue
        await bridge_kosync_percentage(
            db,
            record.user_id,
            book_id,
            record.percentage,
            device=record.device,
            section_index=section_hint_from_xpointer(record.progress),
            xpointer=record.progress,
        )
        bridged += 1
    return bridged
