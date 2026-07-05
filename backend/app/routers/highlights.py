from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.reading import Highlight
from app.models.user import User
from app.schemas.reading import PaginatedHighlights

router = APIRouter(prefix="/api/highlights", tags=["highlights"])


@router.get("", response_model=PaginatedHighlights)
async def get_all_highlights(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get the current user's highlights across all books, paginated.

    Highlights carry full text/note payloads, so an unbounded response
    grows without limit for heavy highlighters.
    """
    total = (
        await db.execute(
            select(func.count())
            .select_from(Highlight)
            .where(Highlight.user_id == current_user.id)
        )
    ).scalar() or 0
    result = await db.execute(
        select(Highlight)
        .where(Highlight.user_id == current_user.id)
        .order_by(Highlight.created_at.desc(), Highlight.id)
        .limit(limit)
        .offset(offset)
    )
    return PaginatedHighlights(items=result.scalars().all(), total=total)
