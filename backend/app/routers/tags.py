"""Tag-related API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.library import LibraryBook, UserLibraryExclusion
from app.models.tag import BookTag
from app.models.user import User, UserRole
from app.schemas.tag import TagWithCount
from app.services.tags import CURATED_TAGS_WITH_LABELS, TAG_LABELS, TAG_LABELS_HANS

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagWithCount])
async def list_tags(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(None),
):
    """List all tags with book counts."""
    query = (
        select(
            BookTag.tag,
            BookTag.category,
            # (book_id, tag) is unique: the rows of a tag are its books.
            func.count().label("book_count"),
        )
        .group_by(BookTag.tag, BookTag.category)
        .order_by(func.count().desc())
    )
    if category:
        query = query.where(BookTag.category == category)
    # A user kept out of some libraries counts only the books they can
    # open. (Asked only then: for everyone else the plain count is the
    # answer, and much the cheaper query.)
    if current_user.role != UserRole.admin:
        excluded = select(UserLibraryExclusion.library_id).where(
            UserLibraryExclusion.user_id == current_user.id
        )
        if (await db.execute(excluded.limit(1))).first() is not None:
            query = query.where(
                BookTag.book_id.in_(
                    select(LibraryBook.book_id).where(
                        LibraryBook.library_id.not_in(excluded)
                    )
                )
            )

    result = await db.execute(query)
    return [
        TagWithCount(
            tag=row[0],
            label=TAG_LABELS.get(row[0], row[0]),
            label_hans=TAG_LABELS_HANS.get(row[0], row[0]),
            category=row[1],
            book_count=row[2],
        )
        for row in result.fetchall()
    ]


@router.get("/vocabulary")
async def get_vocabulary(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, dict[str, str]]:
    """Return the curated tag vocabulary with Chinese labels."""
    return CURATED_TAGS_WITH_LABELS
