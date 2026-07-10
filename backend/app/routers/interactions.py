"""Per-book user interaction endpoints: ratings, favorites, reading
status/progress, highlights, and reports.

Extracted from routers/books.py — same /api/books prefix, so URLs are
unchanged.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.reading import Highlight, ReadingActivity, UserBookInteraction
from app.models.user import User
from app.routers.books import _get_book_with_access, _today_in_app_timezone
from app.schemas.book import BookReportCreate, BookReportOut
from app.schemas.reading import (
    FavoriteUpdate,
    HighlightCreate,
    HighlightOut,
    HighlightUpdate,
    InteractionOut,
    NotesUpdate,
    ProgressOut,
    ProgressUpdate,
    RatingUpdate,
    ReadingStatusUpdate,
)
from app.tasks.text_extract import extract_book_text

router = APIRouter(prefix="/api/books", tags=["interactions"])


@router.get("/{book_id}/interaction", response_model=InteractionOut)
async def get_interaction(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id == book_id,
        )
    )
    interaction = result.scalar_one_or_none()

    if not interaction:
        return InteractionOut(
            rating=None,
            is_favorite=False,
            reading_progress=None,
            reading_status=None,
            started_at=None,
            finished_at=None,
            notes=None,
            updated_at=datetime.now(UTC),
        )
    return interaction


@router.put("/{book_id}/rating")
async def update_rating(
    book_id: uuid.UUID,
    body: RatingUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    if body.rating is not None and not (
        0.5 <= body.rating <= 5 and (body.rating * 2).is_integer()
    ):
        raise HTTPException(status_code=400, detail="Rating must be 0.5-5 in 0.5 steps")
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.rating = body.rating
    await db.commit()
    return {"status": "updated"}


@router.put("/{book_id}/favorite")
async def update_favorite(
    book_id: uuid.UUID,
    body: FavoriteUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _get_book_with_access(book_id, current_user, db)
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.is_favorite = body.is_favorite

    # Sync to all sibling editions in the same Work
    if book.work_id:
        await _sync_sibling_interactions(
            current_user.id,
            book.work_id,
            book_id,
            {"is_favorite": body.is_favorite},
            db,
        )

    await db.commit()
    return {"status": "updated"}


@router.put("/{book_id}/reading-status")
async def update_reading_status(
    book_id: uuid.UUID,
    body: ReadingStatusUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.reading import ReadingStatus

    book = await _get_book_with_access(book_id, current_user, db)
    if body.reading_status is not None:
        valid = {s.value for s in ReadingStatus}
        if body.reading_status not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reading status. Must be one of: {', '.join(valid)}",
            )
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.reading_status = body.reading_status
    interaction.started_at = body.started_at
    interaction.finished_at = body.finished_at

    # Sync to all sibling editions in the same Work
    if book.work_id:
        await _sync_sibling_interactions(
            current_user.id,
            book.work_id,
            book_id,
            {
                "reading_status": body.reading_status,
                "started_at": body.started_at,
                "finished_at": body.finished_at,
            },
            db,
        )

    await db.commit()
    return {"status": "updated"}


@router.put("/{book_id}/notes")
async def update_notes(
    book_id: uuid.UUID,
    body: NotesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.notes = body.notes
    await db.commit()
    return {"status": "updated"}


@router.get("/{book_id}/progress", response_model=ProgressOut)
async def get_progress(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id == book_id,
        )
    )
    interaction = result.scalar_one_or_none()
    if not interaction or not interaction.reading_progress:
        return {}
    return interaction.reading_progress


@router.put("/{book_id}/progress")
async def update_progress(
    book_id: uuid.UUID,
    body: ProgressUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)

    now = datetime.now(UTC)
    # Track reading minutes from time delta (only when triggered by user action)
    if body.track_activity:
        old_last_read = None
        if interaction.reading_progress and interaction.reading_progress.get(
            "last_read_at"
        ):
            try:
                old_last_read = datetime.fromisoformat(
                    interaction.reading_progress["last_read_at"]
                )
            except (ValueError, TypeError):
                pass
        if old_last_read:
            delta = (now - old_last_read).total_seconds()
            MAX_READING_SESSION_GAP = 300  # 5 minutes
            if 0 < delta < MAX_READING_SESSION_GAP:
                delta_seconds = int(delta)
                today = await _today_in_app_timezone(db)
                result = await db.execute(
                    select(ReadingActivity).where(
                        ReadingActivity.user_id == current_user.id,
                        ReadingActivity.date == today,
                    )
                )
                activity = result.scalar_one_or_none()
                if activity:
                    activity.seconds = activity.seconds + delta_seconds
                else:
                    db.add(
                        ReadingActivity(
                            user_id=current_user.id,
                            date=today,
                            seconds=delta_seconds,
                        )
                    )

    progress: dict = {
        "cfi": body.cfi,
        "percentage": body.percentage,
        "last_read_at": now.isoformat(),
    }
    if body.percentage is None:
        # Locations were still generating client-side — don't zero out the
        # stored percentage (possibly bridged from kosync); the next
        # canonical save corrects it.
        prev = (interaction.reading_progress or {}).get("percentage")
        progress["percentage"] = prev
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
    interaction.reading_progress = progress
    await db.commit()

    # Trigger text extraction + summary generation in the background
    if body.section_index is not None:
        from app.tasks.summarize import summarize_chunks

        extract_book_text.delay(str(book_id))
        summarize_chunks.delay(str(book_id), body.section_index)

    return {"status": "updated"}


@router.get("/{book_id}/highlights", response_model=list[HighlightOut])
async def get_highlights(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(Highlight)
        .where(
            Highlight.user_id == current_user.id,
            Highlight.book_id == book_id,
        )
        .order_by(Highlight.created_at.asc())
    )
    return result.scalars().all()


@router.post(
    "/{book_id}/highlights",
    response_model=HighlightOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_highlight(
    book_id: uuid.UUID,
    body: HighlightCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    highlight = Highlight(
        user_id=current_user.id,
        book_id=book_id,
        **body.model_dump(),
    )
    db.add(highlight)
    await db.commit()
    await db.refresh(highlight)
    return highlight


@router.put("/{book_id}/highlights/{highlight_id}", response_model=HighlightOut)
async def update_highlight(
    book_id: uuid.UUID,
    highlight_id: uuid.UUID,
    body: HighlightUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Highlight).where(
            Highlight.id == highlight_id,
            Highlight.user_id == current_user.id,
            Highlight.book_id == book_id,
        )
    )
    highlight = result.scalar_one_or_none()
    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(highlight, field, value)
    await db.commit()
    await db.refresh(highlight)
    return highlight


@router.delete(
    "/{book_id}/highlights/{highlight_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_highlight(
    book_id: uuid.UUID,
    highlight_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Highlight).where(
            Highlight.id == highlight_id,
            Highlight.user_id == current_user.id,
            Highlight.book_id == book_id,
        )
    )
    highlight = result.scalar_one_or_none()
    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")
    await db.delete(highlight)
    await db.commit()


async def _get_or_create_interaction(
    user_id: uuid.UUID, book_id: uuid.UUID, db: AsyncSession
) -> UserBookInteraction:
    # ON CONFLICT DO NOTHING makes concurrent first-interactions (e.g. a
    # double tap racing two requests) converge instead of 500ing on the PK.
    await db.execute(
        pg_insert(UserBookInteraction)
        .values(user_id=user_id, book_id=book_id, is_favorite=False)
        .on_conflict_do_nothing(index_elements=["user_id", "book_id"])
    )
    result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == user_id,
            UserBookInteraction.book_id == book_id,
        )
    )
    return result.scalar_one()


async def _sync_sibling_interactions(
    user_id: uuid.UUID,
    work_id: uuid.UUID,
    exclude_book_id: uuid.UUID,
    values: dict,
    db: AsyncSession,
) -> None:
    """Propagate interaction fields to all sibling editions in one upsert."""
    sib_result = await db.execute(
        select(Book.id).where(Book.work_id == work_id, Book.id != exclude_book_id)
    )
    sibling_ids = [row[0] for row in sib_result.all()]
    if not sibling_ids:
        return
    stmt = pg_insert(UserBookInteraction).values(
        [
            {"user_id": user_id, "book_id": sib_id, "is_favorite": False, **values}
            for sib_id in sibling_ids
        ]
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "book_id"],
            set_={**values, "updated_at": func.now()},
        )
    )


# --- Book Reports ---


@router.post(
    "/{book_id}/reports",
    response_model=BookReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_book_report(
    book_id: uuid.UUID,
    body: BookReportCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.book_report import ISSUE_TYPES, BookReport

    book = await _get_book_with_access(book_id, current_user, db)
    if body.issue_type not in ISSUE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid issue_type. Must be one of: {', '.join(sorted(ISSUE_TYPES))}",
        )
    if body.description and len(body.description) > 2000:
        raise HTTPException(
            status_code=422, detail="Description must be 2000 characters or less"
        )
    report = BookReport(
        book_id=book.id,
        reported_by=current_user.id,
        issue_type=body.issue_type,
        description=body.description,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    out = BookReportOut.model_validate(report)
    out.book_title = book.title or book.epub_title
    out.book_cover = book.cover_path
    return out


@router.get("/{book_id}/reports", response_model=list[BookReportOut])
async def get_book_reports(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.book_report import BookReport

    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(BookReport)
        .where(BookReport.book_id == book_id)
        .order_by(BookReport.created_at.desc())
    )
    reports = result.scalars().all()
    return [BookReportOut.model_validate(r) for r in reports]
