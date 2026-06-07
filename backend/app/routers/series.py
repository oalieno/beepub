import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.reading import UserSeriesInteraction
from app.models.user import User
from app.routers.libraries import _get_accessible_library
from app.schemas.series import SeriesNotesUpdate, SeriesOut, SeriesRatingUpdate
from app.services.series import (
    build_series_out,
    list_series,
    normalize_series_name,
)

router = APIRouter(prefix="/api/series", tags=["series"])


async def _get_or_create_series(
    user_id: uuid.UUID,
    library_id: uuid.UUID,
    series_key: str,
    series_name: str,
    db: AsyncSession,
) -> UserSeriesInteraction:
    result = await db.execute(
        select(UserSeriesInteraction).where(
            UserSeriesInteraction.user_id == user_id,
            UserSeriesInteraction.library_id == library_id,
            UserSeriesInteraction.series_key == series_key,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        row = UserSeriesInteraction(
            user_id=user_id,
            library_id=library_id,
            series_key=series_key,
            series_name=series_name,
        )
        db.add(row)
        await db.flush()
    else:
        # Keep the display name fresh with the latest casing seen.
        row.series_name = series_name
    return row


def _resolve_key(series_name: str) -> str:
    key = normalize_series_name(series_name)
    if not key:
        raise HTTPException(status_code=400, detail="Series name is required")
    return key


@router.get("/rated", response_model=list[SeriesOut])
async def list_rated_series(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Series with an effective rating, across all accessible libraries.

    Used by the tier page — naturally small, so no pagination.
    """
    rows, _ = await list_series(db, current_user, rated_only=True)
    return await build_series_out(db, rows)


@router.get("/detail", response_model=SeriesOut)
async def get_series_detail(
    name: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    library: uuid.UUID | None = None,
):
    """One series by name (the series-detail page).

    Series identity is (library_id, series_key), so the same name in another
    library is a different series. ``library`` pins which one; when omitted (an
    old or shared link with just ?name=), the first matching accessible series is
    returned so the page still resolves.
    """
    key = _resolve_key(name)
    if library is not None:
        await _get_accessible_library(library, current_user, db)
        rows, _ = await list_series(db, current_user, library_id=library, key=key)
    else:
        rows, _ = await list_series(db, current_user, key=key)
    if not rows:
        raise HTTPException(status_code=404, detail="Series not found")
    out = await build_series_out(db, rows)
    return out[0]


@router.put("/rating")
async def update_series_rating(
    body: SeriesRatingUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if body.rating is not None and not (
        0.5 <= body.rating <= 5 and (body.rating * 2).is_integer()
    ):
        raise HTTPException(status_code=400, detail="Rating must be 0.5-5 in 0.5 steps")
    key = _resolve_key(body.series_name)
    await _get_accessible_library(body.library_id, current_user, db)
    row = await _get_or_create_series(
        current_user.id, body.library_id, key, body.series_name.strip(), db
    )
    row.rating = body.rating
    await db.commit()
    return {"status": "updated"}


@router.put("/notes")
async def update_series_notes(
    body: SeriesNotesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    key = _resolve_key(body.series_name)
    await _get_accessible_library(body.library_id, current_user, db)
    row = await _get_or_create_series(
        current_user.id, body.library_id, key, body.series_name.strip(), db
    )
    row.notes = body.notes
    await db.commit()
    return {"status": "updated"}
