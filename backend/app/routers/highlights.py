from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.reading import Highlight
from app.schemas.reading import HighlightOut

router = APIRouter(prefix="/api/highlights", tags=["highlights"])


@router.get("", response_model=list[HighlightOut])
async def get_all_highlights(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get all highlights for the current user across all books."""
    result = await db.execute(
        select(Highlight)
        .where(Highlight.user_id == current_user.id)
        .order_by(Highlight.created_at.desc())
    )
    return result.scalars().all()
