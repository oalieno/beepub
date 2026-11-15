"""The library's lists of books: flat, and grouped by series."""

import logging
import uuid
from typing import Annotated, Any, NamedTuple

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import coalesce

from app.database import get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.library import LibraryBook
from app.models.reading import UserBookInteraction
from app.models.tag import BookTag
from app.models.user import User
from app.schemas.book import (
    PaginatedBooksWithInteraction,
)
from app.schemas.series import PaginatedGrouped
from app.services.access import (
    accessible_book_ids_select,
    get_accessible_library,
)
from app.services.book_cards import book_cards
from app.services.book_search import relevance_ranked_ids, tiered_book_search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


class _Place(NamedTuple):
    """Where a book stands in the list: how many come before it, and —
    when the order is one key and the id — that key and the book's own
    value of it (None when numbering every row was the only way)."""

    index: int
    key: Any = None
    value: Any = None
    book_id: uuid.UUID | None = None

    def before(self, order: str):
        tie = and_(self.key == self.value, Book.id < self.book_id)
        if order == "desc":
            # Descending, Postgres puts the books with no key first.
            return or_(self.key > self.value, self.key.is_(None), tie)
        return or_(self.key < self.value, tie)

    def from_here(self, order: str):
        tie = and_(self.key == self.value, Book.id >= self.book_id)
        if order == "desc":
            return or_(self.key < self.value, tie)
        return or_(self.key > self.value, self.key.is_(None), tie)


async def _place_in_order(
    db: AsyncSession,
    base_query,
    book_id: uuid.UUID,
    sort: str,
    order: str,
    order_by: list,
) -> _Place | None:
    """The book's place in the list in the given order (None when it is
    not in the list).

    Counted, where the order is one key and the id: the books whose key
    sorts before this book's — a walk of the key's index up to the book,
    where numbering every row of the list sorts all of it first."""
    if sort != "series_index":
        key = order_by[0].element
        found = (
            await db.execute(
                base_query.with_only_columns(key).where(Book.id == book_id)
            )
        ).first()
        if found is None:
            return None
        if found[0] is not None:
            place = _Place(0, key, found[0], book_id)
            count = await db.scalar(
                select(func.count()).select_from(
                    base_query.with_only_columns(Book.id)
                    .where(place.before(order))
                    .subquery()
                )
            )
            return place._replace(index=count or 0)
    ranked = base_query.with_only_columns(
        Book.id.label("id"),
        func.row_number().over(order_by=order_by).label("rn"),
    ).subquery()
    rank = await db.scalar(select(ranked.c.rn).where(ranked.c.id == book_id))
    return None if rank is None else _Place(rank - 1)


async def _page_at(
    db: AsyncSession, base_query, place: _Place, order: str, limit: int
) -> list[Book]:
    """The page that opens AROUND_BEFORE books ahead of the place: those
    few, read backwards from it, then the rest forwards — two short walks
    from the book, where an OFFSET walks the whole list up to it."""
    key = place.key
    backwards = (
        [key.asc(), Book.id.desc()] if order == "desc" else [key.desc(), Book.id.desc()]
    )
    forwards = [key.desc(), Book.id] if order == "desc" else [key.asc(), Book.id]
    ahead = list(
        await db.scalars(
            base_query.where(place.before(order))
            .order_by(*backwards)
            .limit(min(AROUND_BEFORE, place.index))
        )
    )
    ahead.reverse()
    # (The page is `limit` books from its start, wherever the book falls.)
    ahead = ahead[:limit]
    if len(ahead) == limit:
        return ahead
    rest = list(
        await db.scalars(
            base_query.where(place.from_here(order))
            .order_by(*forwards)
            .limit(limit - len(ahead))
        )
    )
    return ahead + rest


# How many books the page opened ``around`` a book shows before it.
AROUND_BEFORE = 20


def _list_order(sort: str, order: str) -> list:
    """The flat book list's ORDER BY — ending on Book.id, so the order is
    total and a book's place in it (``around``) is the place it is paged at."""
    sort_map = {
        "display_title": coalesce(Book.title, Book.epub_title),
        "added_at": coalesce(Book.calibre_added_at, Book.created_at),
        "series_index": coalesce(Book.series_index, Book.epub_series_index),
        "popularity_score": Book.popularity_score,
    }
    # A column of the table by its name, or the newest first: any other
    # attribute of the model (a relationship, `metadata`) is not an order.
    sort_col = sort_map.get(sort)
    if sort_col is None:
        sort_col = (
            getattr(Book, sort) if sort in Book.__table__.columns else Book.created_at
        )
    if sort == "series_index":
        series_col = coalesce(Book.series, Book.epub_series)
        if order == "desc":
            return [series_col.desc().nullslast(), sort_col.desc().nullslast(), Book.id]
        return [series_col.asc().nullslast(), sort_col.asc().nullslast(), Book.id]
    if order == "desc":
        return [sort_col.desc(), Book.id]
    return [sort_col.asc(), Book.id]


@router.get("", response_model=PaginatedBooksWithInteraction)
async def list_all_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    series: str | None = Query(None),
    format: str | None = Query(None),
    library: uuid.UUID | None = Query(None),
    ids: list[uuid.UUID] | None = Query(None, max_length=200),
    has_rating: bool = Query(False),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    around: uuid.UUID | None = Query(None),
):
    """The flat book list: one row per book, across every accessible library.

    ``library`` scopes the result to one library (404 when it does not exist,
    403 when the user is excluded from it) — a library's own page, and with
    ``series`` the series-detail page, which only shows that library's volumes
    (series identity is ``(library_id, series_key)``).

    ``ids`` narrows to the given books — the app's "downloaded" shelf, whose
    membership lives on the device; it pages the ids itself.

    ``around`` opens the page on a book instead of at ``offset``: it starts
    a few books before it (the library table keeps the book in view when its
    order changes). A book not in the list leaves ``offset`` as asked; the
    response's ``around_index`` says which happened.
    """

    if library is not None:
        await get_accessible_library(library, current_user, db)

    # Accessible book IDs (avoids DISTINCT on the main query)
    accessible_ids = accessible_book_ids_select(current_user)

    base_query = select(Book).where(Book.id.in_(accessible_ids))
    if ids:
        base_query = base_query.where(Book.id.in_(ids))

    # Apply filters. Search is applied last, below — its tier probe must
    # see the fully-filtered scope.
    if author:
        base_query = base_query.where(
            or_(
                Book.authors.any(author),
                Book.epub_authors.any(author),
            )
        )
    if tag:
        base_query = base_query.where(
            or_(
                Book.tags.any(tag),
                Book.epub_tags.any(tag),
                Book.id.in_(select(BookTag.book_id).where(BookTag.tag == tag)),
            )
        )
    if series:
        base_query = base_query.where(
            or_(
                Book.series == series,
                Book.epub_series == series,
            )
        )
    if format:
        base_query = base_query.where(Book.format == format)
    if library:
        base_query = base_query.where(
            Book.id.in_(
                select(LibraryBook.book_id).where(LibraryBook.library_id == library)
            )
        )
    if has_rating:
        base_query = base_query.where(
            Book.id.in_(
                select(UserBookInteraction.book_id).where(
                    UserBookInteraction.user_id == current_user.id,
                    UserBookInteraction.rating.is_not(None),
                )
            )
        )
    tiered = None
    if search:
        tiered = await tiered_book_search(db, search, base_query)
        base_query = base_query.where(or_(*tiered.conditions))

    if ids or author or tag or series or format or has_rating or search:
        # Count over ids — the total needs nothing else from a book.
        count_query = select(func.count()).select_from(
            base_query.with_only_columns(Book.id).subquery()
        )
    else:
        # Nothing about the books themselves is asked: the count is of
        # their places in the libraries (a book has exactly one), without
        # reading the books table — on every page of an endless list.
        placed = accessible_ids
        if library:
            placed = placed.where(LibraryBook.library_id == library)
        count_query = select(func.count()).select_from(placed.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply sorting and pagination
    if series and sort == "created_at":
        sort = "series_index"
        order = "asc"
    if sort == "relevance" and tiered is None:
        # Nothing to be relevant to (a stale URL) — the default order.
        sort, order = "created_at", "desc"
    around_index: int | None = None
    if sort == "relevance":
        # Ranked over ids, the page's books fetched afterwards (see
        # relevance_ranked_ids). ``around`` does not apply: a search starts
        # from its best match.
        page_ids = list(
            await db.scalars(
                relevance_ranked_ids(base_query, tiered, search)
                .offset(offset)
                .limit(limit)
            )
        )
        books_by_id = {
            book.id: book
            for book in await db.scalars(select(Book).where(Book.id.in_(page_ids)))
        }
        books = [books_by_id[book_id] for book_id in page_ids]
    else:
        order_by = _list_order(sort, order)
        if around is not None:
            # The book's place in this very order, so the page can open on it.
            place = await _place_in_order(db, base_query, around, sort, order, order_by)
        if around is not None and place is not None:
            around_index = place.index
            offset = max(0, around_index - AROUND_BEFORE)
        if around is not None and place is not None and place.key is not None:
            books = await _page_at(db, base_query, place, order, limit)
        else:
            result = await db.execute(
                base_query.order_by(*order_by).offset(offset).limit(limit)
            )
            books = result.scalars().all()

    items = await book_cards(db, current_user.id, books)

    return PaginatedBooksWithInteraction(
        items=items, total=total, offset=offset, around_index=around_index
    )


@router.get("/grouped", response_model=PaginatedGrouped)
async def list_books_grouped(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    library: uuid.UUID | None = Query(None),
    sort: str = Query("added_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The grouped book list: a series is one item, editions of the same work
    are one item, every other book is its own.

    ``library`` scopes the result to one library (404 when it does not exist,
    403 when the user is excluded from it); without it the list spans every
    accessible library.
    """
    from app.services.series import list_grouped_books

    # The service does not apply the exclusion filter when scoped to one
    # library, so access to that library is settled here.
    if library is not None:
        await get_accessible_library(library, current_user, db)

    items, total = await list_grouped_books(
        db,
        current_user,
        library_id=library,
        search=search,
        author=author,
        tag=tag,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return PaginatedGrouped(items=items, total=total)
