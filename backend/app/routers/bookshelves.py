import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.book import Book
from app.models.bookshelf import Bookshelf, BookshelfBook
from app.schemas.book import BookOut
from app.schemas.bookshelf import BookshelfCreate, BookshelfUpdate, BookshelfOut, BookshelfBookAdd, BookshelfReorder

router = APIRouter(prefix="/api/bookshelves", tags=["bookshelves"])


@router.get("", response_model=list[BookshelfOut])
async def list_bookshelves(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Bookshelf).where(Bookshelf.user_id == current_user.id).order_by(Bookshelf.created_at.desc())
    )
    return result.scalars().all()


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


@router.get("/{shelf_id}/books", response_model=list[BookOut])
async def list_shelf_books(
    shelf_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_owned_shelf(shelf_id, current_user, db)
    result = await db.execute(
        select(Book)
        .join(BookshelfBook, BookshelfBook.book_id == Book.id)
        .where(BookshelfBook.bookshelf_id == shelf_id)
        .order_by(BookshelfBook.sort_order.asc())
    )
    return result.scalars().all()


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
        select(BookshelfBook).where(BookshelfBook.bookshelf_id == shelf_id).order_by(BookshelfBook.sort_order.desc())
    )
    last = result.scalars().first()
    sort_order = (last.sort_order + 1) if last else 0
    bb = BookshelfBook(bookshelf_id=shelf_id, book_id=body.book_id, sort_order=sort_order)
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


async def _get_owned_shelf(shelf_id: uuid.UUID, user: User, db: AsyncSession) -> Bookshelf:
    result = await db.execute(
        select(Bookshelf).where(Bookshelf.id == shelf_id, Bookshelf.user_id == user.id)
    )
    shelf = result.scalar_one_or_none()
    if not shelf:
        raise HTTPException(status_code=404, detail="Bookshelf not found")
    return shelf
