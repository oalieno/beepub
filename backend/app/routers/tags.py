"""Tag-related API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.tag import AiBookTag
from app.models.user import User
from app.schemas.tag import TagWithCount
from app.services.tags import CURATED_TAGS_WITH_LABELS, TAG_LABELS

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagWithCount])
async def list_tags(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(None),
):
    """List all AI tags with book counts."""
    query = (
        select(
            AiBookTag.tag,
            AiBookTag.category,
            func.count(func.distinct(AiBookTag.book_id)).label("book_count"),
        )
        .group_by(AiBookTag.tag, AiBookTag.category)
        .order_by(func.count(func.distinct(AiBookTag.book_id)).desc())
    )
    if category:
        query = query.where(AiBookTag.category == category)

    result = await db.execute(query)
    return [
        TagWithCount(
            tag=row[0],
            label=TAG_LABELS.get(row[0], row[0]),
            category=row[1],
            book_count=row[2],
        )
        for row in result.fetchall()
    ]


@router.get("/vocabulary")
async def get_vocabulary() -> dict[str, dict[str, str]]:
    """Return the curated tag vocabulary with Chinese labels."""
    return CURATED_TAGS_WITH_LABELS
