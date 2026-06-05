import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.bookshelf import Bookshelf, BookshelfBook
from app.models.user import User
from app.schemas.bookshelf import (
    BookshelfBookAdd,
    BookshelfCreate,
    BookshelfListOut,
    BookshelfOut,
    BookshelfReorder,
    BookshelfSeriesAdd,
    BookshelfUpdate,
)
from app.schemas.series import LibraryFeedItem
from app.services.series import (
    _hydrate_feed_books,
    build_series_out,
    list_series,
    normalize_series_name,
)

router = APIRouter(prefix="/api/bookshelves", tags=["bookshelves"])


@router.get("", response_model=list[BookshelfListOut])
async def list_bookshelves(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Bookshelf)
        .where(Bookshelf.user_id == current_user.id)
        .order_by(Bookshelf.created_at.desc())
    )
    shelves = result.scalars().all()

    if not shelves:
        return []

    shelf_ids = [s.id for s in shelves]

    # Batch query: book counts per shelf
    count_result = await db.execute(
        select(BookshelfBook.bookshelf_id, func.count())
        .where(BookshelfBook.bookshelf_id.in_(shelf_ids))
        .group_by(BookshelfBook.bookshelf_id)
    )
    counts = dict(count_result.all())

    # Preview covers (up to 4 per shelf, in sort order) — a member can be a
    # book (its own cover) or a series (a representative volume's cover).
    membership = (
        await db.execute(
            select(
                BookshelfBook.bookshelf_id,
                BookshelfBook.book_id,
                BookshelfBook.series_key,
            )
            .where(BookshelfBook.bookshelf_id.in_(shelf_ids))
            .order_by(BookshelfBook.bookshelf_id, BookshelfBook.sort_order.asc())
        )
    ).all()

    member_book_ids = [r.book_id for r in membership if r.book_id is not None]
    books_with_cover: set = set()
    if member_book_ids:
        rows = await db.execute(
            select(Book.id).where(
                Book.id.in_(member_book_ids), Book.cover_path.isnot(None)
            )
        )
        books_with_cover = {bid for (bid,) in rows.all()}

    # First volume with a cover, per series key.
    series_keys = list({r.series_key for r in membership if r.series_key is not None})
    series_cover: dict[str, uuid.UUID] = {}
    if series_keys:
        rows = await db.execute(
            text("""
                SELECT series_key, cover_book_id FROM (
                    SELECT
                        lower(btrim(coalesce(b.series, b.epub_series))) AS series_key,
                        b.id AS cover_book_id,
                        row_number() OVER (
                            PARTITION BY
                                lower(btrim(coalesce(b.series, b.epub_series)))
                            ORDER BY coalesce(b.series_index, b.epub_series_index)
                                ASC NULLS LAST, b.created_at ASC
                        ) AS rn
                    FROM books b
                    WHERE b.cover_path IS NOT NULL
                      AND lower(btrim(coalesce(b.series, b.epub_series)))
                          = ANY(:keys)
                ) t WHERE rn = 1
            """),
            {"keys": series_keys},
        )
        series_cover = {row.series_key: row.cover_book_id for row in rows}

    previews: dict[str, list] = {}
    for r in membership:
        lst = previews.setdefault(r.bookshelf_id, [])
        if len(lst) >= 4:
            continue
        if r.book_id is not None:
            if r.book_id in books_with_cover:
                lst.append(r.book_id)
        else:
            cover = series_cover.get(r.series_key)
            if cover is not None:
                lst.append(cover)

    return [
        BookshelfListOut(
            **{c.key: getattr(s, c.key) for c in s.__table__.columns},
            book_count=counts.get(s.id, 0),
            preview_book_ids=previews.get(s.id, []),
        )
        for s in shelves
    ]


@router.post("", response_model=BookshelfOut, status_code=status.HTTP_201_CREATED)
async def create_bookshelf(
    body: BookshelfCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    shelf = Bookshelf(**body.model_dump(), user_id=current_user.id)
    db.add(shelf)
    await db.commit()
    await db.refresh(shelf)
    return shelf


@router.get("/{shelf_id}", response_model=BookshelfOut)
async def get_bookshelf(
    shelf_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _get_owned_shelf(shelf_id, current_user, db)


@router.put("/{shelf_id}", response_model=BookshelfOut)
async def update_bookshelf(
    shelf_id: uuid.UUID,
    body: BookshelfUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    shelf = await _get_owned_shelf(shelf_id, current_user, db)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(shelf, field, value)
    await db.commit()
    await db.refresh(shelf)
    return shelf


@router.delete("/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookshelf(
    shelf_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    shelf = await _get_owned_shelf(shelf_id, current_user, db)
    await db.delete(shelf)
    await db.commit()


@router.get("/{shelf_id}/items", response_model=list[LibraryFeedItem])
async def list_shelf_items(
    shelf_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Shelf contents in sort order: each row is a book or a whole series,
    hydrated with the same rating/interaction data the feed endpoints use."""
    await _get_owned_shelf(shelf_id, current_user, db)
    result = await db.execute(
        select(BookshelfBook)
        .where(BookshelfBook.bookshelf_id == shelf_id)
        .order_by(BookshelfBook.sort_order.asc())
    )
    rows = result.scalars().all()

    book_ids = [r.book_id for r in rows if r.book_id is not None]
    series_keys = [r.series_key for r in rows if r.series_key is not None]

    book_by_id = await _hydrate_feed_books(db, current_user, book_ids)
    series_by_key: dict = {}
    if series_keys:
        srows, _ = await list_series(db, current_user, keys=series_keys)
        for s in await build_series_out(db, srows):
            series_by_key[s.series_key] = s

    items: list[LibraryFeedItem] = []
    for r in rows:
        if r.book_id is not None:
            book = book_by_id.get(r.book_id)
            if book is not None:
                items.append(LibraryFeedItem(type="book", book=book))
        else:
            series = series_by_key.get(r.series_key)
            if series is not None:
                items.append(LibraryFeedItem(type="series", series=series))
    return items


@router.post("/{shelf_id}/books", status_code=status.HTTP_201_CREATED)
async def add_book_to_shelf(
    shelf_id: uuid.UUID,
    body: BookshelfBookAdd,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_owned_shelf(shelf_id, current_user, db)
    existing = await db.execute(
        select(BookshelfBook).where(
            BookshelfBook.bookshelf_id == shelf_id,
            BookshelfBook.book_id == body.book_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Book already in shelf")
    # Get max sort order
    result = await db.execute(
        select(BookshelfBook)
        .where(BookshelfBook.bookshelf_id == shelf_id)
        .order_by(BookshelfBook.sort_order.desc())
    )
    last = result.scalars().first()
    sort_order = (last.sort_order + 1) if last else 0
    bb = BookshelfBook(
        bookshelf_id=shelf_id, book_id=body.book_id, sort_order=sort_order
    )
    db.add(bb)
    await db.commit()
    return {"status": "added"}


@router.delete("/{shelf_id}/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_book_from_shelf(
    shelf_id: uuid.UUID,
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_owned_shelf(shelf_id, current_user, db)
    result = await db.execute(
        select(BookshelfBook).where(
            BookshelfBook.bookshelf_id == shelf_id,
            BookshelfBook.book_id == book_id,
        )
    )
    bb = result.scalar_one_or_none()
    if not bb:
        raise HTTPException(status_code=404, detail="Book not in shelf")
    await db.delete(bb)
    await db.commit()


@router.post("/{shelf_id}/series", status_code=status.HTTP_201_CREATED)
async def add_series_to_shelf(
    shelf_id: uuid.UUID,
    body: BookshelfSeriesAdd,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_owned_shelf(shelf_id, current_user, db)
    key = normalize_series_name(body.series_name)
    if not key:
        raise HTTPException(status_code=422, detail="Invalid series name")
    existing = await db.execute(
        select(BookshelfBook).where(
            BookshelfBook.bookshelf_id == shelf_id,
            BookshelfBook.series_key == key,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Series already in shelf")
    result = await db.execute(
        select(BookshelfBook)
        .where(BookshelfBook.bookshelf_id == shelf_id)
        .order_by(BookshelfBook.sort_order.desc())
    )
    last = result.scalars().first()
    sort_order = (last.sort_order + 1) if last else 0
    db.add(BookshelfBook(bookshelf_id=shelf_id, series_key=key, sort_order=sort_order))
    await db.commit()
    return {"status": "added"}


@router.delete("/{shelf_id}/series", status_code=status.HTTP_204_NO_CONTENT)
async def remove_series_from_shelf(
    shelf_id: uuid.UUID,
    key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_owned_shelf(shelf_id, current_user, db)
    result = await db.execute(
        select(BookshelfBook).where(
            BookshelfBook.bookshelf_id == shelf_id,
            BookshelfBook.series_key == key,
        )
    )
    bb = result.scalar_one_or_none()
    if not bb:
        raise HTTPException(status_code=404, detail="Series not in shelf")
    await db.delete(bb)
    await db.commit()


@router.put("/{shelf_id}/books/reorder")
async def reorder_shelf_books(
    shelf_id: uuid.UUID,
    body: BookshelfReorder,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_owned_shelf(shelf_id, current_user, db)
    for i, book_id in enumerate(body.book_ids):
        result = await db.execute(
            select(BookshelfBook).where(
                BookshelfBook.bookshelf_id == shelf_id,
                BookshelfBook.book_id == book_id,
            )
        )
        bb = result.scalar_one_or_none()
        if bb:
            bb.sort_order = i
    await db.commit()
    return {"status": "reordered"}


async def _get_owned_shelf(
    shelf_id: uuid.UUID, user: User, db: AsyncSession
) -> Bookshelf:
    result = await db.execute(
        select(Bookshelf).where(Bookshelf.id == shelf_id, Bookshelf.user_id == user.id)
    )
    shelf = result.scalar_one_or_none()
    if not shelf:
        raise HTTPException(status_code=404, detail="Bookshelf not found")
    return shelf
