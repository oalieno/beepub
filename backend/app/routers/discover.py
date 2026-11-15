"""Finding something to read: a random draw, recommendations, and the
discover page's shelves by tag.

Same ``/api/books`` prefix as the rest (the URLs predate the split), and
registered before ``books.router``: these paths are fixed words where
that router has ``/{book_id}``.
"""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.library import Library, LibraryBook
from app.models.user import User, UserRole
from app.schemas.book import (
    BookOut,
    BookWithInteractionOut,
)
from app.services.access import (
    accessible_libraries_condition,
)
from app.services.book_cards import book_cards

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("/random", response_model=list[BookOut])
async def get_random_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    count: int = Query(8, ge=1, le=20),
):

    accessible_books = select(LibraryBook.book_id).join(
        Library, Library.id == LibraryBook.library_id
    )
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_books = accessible_books.where(cond)
    accessible_book_ids = accessible_books.subquery()

    # Drawn over ids, the books fetched afterwards: shuffling whole rows
    # sorts the entire table's worth of them.
    drawn = list(
        await db.scalars(
            select(Book.id)
            .where(
                Book.id.in_(select(accessible_book_ids.c.book_id)),
                Book.cover_path.isnot(None),
            )
            .order_by(func.random())
            .limit(count)
        )
    )
    by_id = {
        book.id: book
        for book in await db.scalars(select(Book).where(Book.id.in_(drawn)))
    }
    # An empty library is not an error — the frontend renders its own
    # "nothing to pull" state for an empty list.
    return [by_id[book_id] for book_id in drawn if book_id in by_id]


@router.get("/discover/recommendations", response_model=list[BookWithInteractionOut])
async def get_discover_recommendations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(30, ge=1, le=50),
):
    """Personalized book recommendations based on reading history."""
    from app.services.recommendations import get_personalized_recommendations

    recs = await get_personalized_recommendations(
        db,
        current_user.id,
        is_admin=current_user.role == UserRole.admin,
        limit=limit,
    )
    if not recs:
        return []

    book_ids = [r["book_id"] for r in recs]

    result = await db.execute(select(Book).where(Book.id.in_(book_ids)))
    books = {b.id: b for b in result.scalars().all()}

    # Build seed_book_id map for "Because you read X" attribution
    seed_map = {r["book_id"]: r.get("seed_book_id") for r in recs}

    # Fetch seed book titles
    seed_ids = {sid for sid in seed_map.values() if sid}
    seed_titles = {}
    if seed_ids:
        seed_result = await db.execute(
            select(Book.id, Book.title, Book.epub_title).where(Book.id.in_(seed_ids))
        )
        for row in seed_result.all():
            seed_titles[row[0]] = row[1] or row[2] or ""

    items = await book_cards(
        db, current_user.id, [books[bid] for bid in book_ids if bid in books]
    )
    for item in items:
        seed_id = seed_map.get(item.id)
        item.seed_book_id = seed_id
        if seed_id:
            item.seed_book_title = seed_titles.get(seed_id)
    return items


@router.get("/discover/browse")
async def get_discover_browse(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str = Query(..., pattern="^(genre|subgenre|mood|theme|trope)$"),
    limit_per_tag: int = Query(8, ge=1, le=20),
    max_tags: int = Query(10, ge=1, le=30),
):
    """Browse books by tag category."""
    from app.schemas.tag import TagBrowseSection
    from app.services.recommendations import get_books_by_tag_category
    from app.services.tags import TAG_LABELS, TAG_LABELS_HANS

    sections_data = await get_books_by_tag_category(
        db,
        current_user.id,
        is_admin=current_user.role == UserRole.admin,
        category=category,
        limit_per_tag=limit_per_tag,
        max_tags=max_tags,
    )

    all_ids = {bid for s in sections_data for bid in s["book_ids"]}
    if all_ids:
        result = await db.execute(select(Book).where(Book.id.in_(all_ids)))
        book_map = {b.id: b for b in result.scalars().all()}
    else:
        book_map = {}

    cards = {
        card.id: card
        for card in await book_cards(db, current_user.id, list(book_map.values()))
    }

    sections = []
    for section in sections_data:
        if not section["book_ids"]:
            continue
        books = [cards[bid] for bid in section["book_ids"] if bid in cards]
        sections.append(
            TagBrowseSection(
                tag=section["tag"],
                label=TAG_LABELS.get(section["tag"], section["tag"]),
                label_hans=TAG_LABELS_HANS.get(section["tag"], section["tag"]),
                category=section["category"],
                book_count=section["book_count"],
                books=books,
            )
        )

    return sections
