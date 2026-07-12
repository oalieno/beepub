"""Reading-state sync for device-local libraries.

The iOS app can import EPUBs directly onto the device; those books have no
server identity until they are *linked* — matched to a server book by the
KOReader partial-md5 digest (the same file identity kosync uses). This
router serves that flow: a batch digest lookup so a whole local shelf links
in one round trip, and a per-book sync endpoint that merges the device's
reading state with the server's.

Unlike the interactive endpoints in routers/interactions.py — where the
server stamps every timestamp — sync endpoints treat the client as the
authority on when its writes happened; the merge is last-write-wins with
the server winning ties. That contract difference is why they live in
their own module.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.reading import Highlight, UserBookInteraction
from app.models.user import User
from app.routers.books import _get_book_with_access
from app.routers.interactions import _get_or_create_interaction
from app.routers.libraries import accessible_book_ids_select
from app.schemas.reading import (
    BookSyncRequest,
    BookSyncResponse,
    HighlightSyncOut,
    SyncProgressIn,
)
from app.tasks.text_extract import extract_book_text

router = APIRouter(prefix="/api/books", tags=["device-sync"])


class DigestLookupRequest(BaseModel):
    digests: list[Annotated[str, Field(min_length=32, max_length=32)]] = Field(
        max_length=500
    )


class DigestMatch(BaseModel):
    id: uuid.UUID
    title: str | None


class DigestLookupResponse(BaseModel):
    matches: dict[str, DigestMatch]


@router.post("/by-digest", response_model=DigestLookupResponse)
async def lookup_books_by_digest(
    body: DigestLookupRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Resolve KOReader partial-md5 digests to accessible books.

    Digests with no accessible match are simply absent from the response.
    When several editions share a digest, the earliest-created book wins —
    an arbitrary but deterministic pick (kosync's resolver has the same
    ambiguity).
    """
    if not body.digests:
        return DigestLookupResponse(matches={})
    result = await db.execute(
        select(Book.partial_md5, Book.id, Book.title, Book.epub_title)
        .where(
            Book.partial_md5.in_(body.digests),
            Book.id.in_(accessible_book_ids_select(current_user)),
        )
        .order_by(Book.created_at.asc())
    )
    matches: dict[str, DigestMatch] = {}
    for digest, book_id, title, epub_title in result.all():
        if digest in matches:
            continue
        matches[digest] = DigestMatch(id=book_id, title=title or epub_title)
    return DigestLookupResponse(matches=matches)


async def _merge_highlights(
    db: AsyncSession,
    user_id: uuid.UUID,
    book_id: uuid.UUID,
    incoming: list,
) -> None:
    """Batch LWW upsert of client highlight records.

    Client timestamps go into the row verbatim (a Core upsert bypasses the
    ORM's onupdate, the same property the idempotent create relies on).
    The WHERE guard makes every conflict a per-row decision: rows owned by
    another user or book update nothing (silently skipped — a batch must
    not 409 wholesale), and an incoming stamp that isn't strictly newer
    loses, so ties keep the server copy. Tombstones are just a field under
    LWW — a newer client deletion beats a live server row, a stale client
    copy can't resurrect a newer server tombstone, and a newer client edit
    revives one.
    """
    # Same statement may not touch one row twice (Postgres rejects it) —
    # keep the newest copy per id.
    by_id: dict[uuid.UUID, dict] = {}
    for item in incoming:
        candidate = {
            "id": item.id,
            "user_id": user_id,
            "book_id": book_id,
            "cfi_range": item.cfi_range,
            "text": item.text,
            "color": item.color,
            "note": item.note,
            "prefix": item.prefix,
            "suffix": item.suffix,
            "section_index": item.section_index,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "deleted_at": item.deleted_at,
        }
        existing = by_id.get(item.id)
        if existing is None or existing["updated_at"] < item.updated_at:
            by_id[item.id] = candidate
    if not by_id:
        return

    stmt = pg_insert(Highlight).values(list(by_id.values()))
    content_cols = [
        "cfi_range",
        "text",
        "color",
        "note",
        "prefix",
        "suffix",
        "section_index",
        "updated_at",
        "deleted_at",
    ]
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"],
            # created_at is never overwritten — identity stays stable.
            set_={col: stmt.excluded[col] for col in content_cols},
            where=(Highlight.user_id == user_id)
            & (Highlight.book_id == book_id)
            & (Highlight.updated_at < stmt.excluded.updated_at),
        )
    )


def _stored_last_read(progress: dict | None) -> datetime | None:
    if not progress or not progress.get("last_read_at"):
        return None
    try:
        parsed = datetime.fromisoformat(progress["last_read_at"])
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _rebuilt_progress(body: SyncProgressIn, previous: dict | None) -> dict:
    """The stored dict for a client win — PUT /progress semantics with the
    client's own timestamp, and no kosync marker (the rebuild dropping the
    marker is what encodes "the app moved last" for e-reader ordering)."""
    progress: dict = {
        "cfi": body.cfi,
        "percentage": body.percentage,
        "last_read_at": body.last_read_at.isoformat(),
    }
    if body.percentage is None:
        progress["percentage"] = (previous or {}).get("percentage")
    if body.current_page is not None:
        progress["current_page"] = body.current_page
    if body.font_size is not None:
        progress["font_size"] = body.font_size
    if body.section_index is not None:
        progress["section_index"] = body.section_index
    if body.section_page is not None:
        progress["section_page"] = body.section_page
    if body.section_page_counts is not None:
        progress["section_page_counts"] = body.section_page_counts
    if body.total_pages is not None:
        progress["total_pages"] = body.total_pages
    if body.xpointer is not None:
        progress["xpointer"] = body.xpointer
    return progress


@router.post("/{book_id}/sync", response_model=BookSyncResponse)
async def sync_reading_state(
    book_id: uuid.UUID,
    body: BookSyncRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Merge a device's reading state for one book and return the result.

    Highlights: per-row LWW by updated_at with tombstone union; the
    response is the full post-merge set INCLUDING tombstones, so the
    device can apply remote deletions. Progress: single winner by
    last_read_at (ties → server). Synced progress never records reading
    activity — streaks stay a live-reading signal.
    """
    await _get_book_with_access(book_id, current_user, db)

    if body.highlights:
        await _merge_highlights(db, current_user.id, book_id, body.highlights)

    client_won = False
    if body.progress is not None:
        interaction = await _get_or_create_interaction(current_user.id, book_id, db)
        server_last = _stored_last_read(interaction.reading_progress)
        if server_last is None or body.progress.last_read_at > server_last:
            interaction.reading_progress = _rebuilt_progress(
                body.progress, interaction.reading_progress
            )
            client_won = True

    await db.commit()

    if (
        client_won
        and body.progress is not None
        and body.progress.section_index is not None
    ):
        from app.tasks.summarize import summarize_chunks

        extract_book_text.delay(str(book_id))
        summarize_chunks.delay(str(book_id), body.progress.section_index)

    result = await db.execute(
        select(Highlight)
        .where(Highlight.user_id == current_user.id, Highlight.book_id == book_id)
        .order_by(Highlight.created_at.asc())
    )
    highlights = [HighlightSyncOut.model_validate(h) for h in result.scalars().all()]

    interaction_result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id == book_id,
        )
    )
    final = interaction_result.scalar_one_or_none()
    return BookSyncResponse(
        progress=final.reading_progress if final else None,
        highlights=highlights,
    )
