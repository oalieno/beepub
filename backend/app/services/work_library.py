"""Invariant: every Book lives in at most one Library, and every Book in a
Work shares that Library with its Work siblings.

Why: /books/me's display logic relies on the primary edition of a Work being
accessible to any user who can access any sibling. Holding "all editions in
a Work share a single library" + "books are 1:N library" guarantees that.

These helpers are the gatekeepers; they don't write to the DB themselves.
Callers raise HTTP errors from the ValueError messages.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.library import LibraryBook


async def get_book_library_id(book_id: uuid.UUID, db: AsyncSession) -> uuid.UUID | None:
    """Return the single library a book belongs to, or None if unassigned.

    Raises ValueError if the book is in multiple libraries (1:N invariant
    violation; should never happen under the validation in this module).
    """
    result = await db.execute(
        select(LibraryBook.library_id).where(LibraryBook.book_id == book_id)
    )
    library_ids = list(result.scalars().all())
    if len(library_ids) > 1:
        raise ValueError(
            f"Book {book_id} is in multiple libraries ({library_ids}); "
            "expected at most 1"
        )
    return library_ids[0] if library_ids else None


async def assert_books_share_single_library(
    book_ids: list[uuid.UUID], db: AsyncSession
) -> uuid.UUID | None:
    """Validate that every book is in at most one library, and all listed
    books share the same library. Returns the shared library_id (or None if
    no books are assigned). Raises ValueError on violation.
    """
    if not book_ids:
        return None
    result = await db.execute(
        select(LibraryBook.book_id, LibraryBook.library_id).where(
            LibraryBook.book_id.in_(book_ids)
        )
    )
    by_book: dict[uuid.UUID, uuid.UUID] = {}
    for bid, lid in result.all():
        if bid in by_book and by_book[bid] != lid:
            raise ValueError(f"Book {bid} is in multiple libraries; expected 1:N")
        by_book[bid] = lid

    library_ids = set(by_book.values())
    if len(library_ids) > 1:
        raise ValueError(
            f"Books span multiple libraries: {sorted(map(str, library_ids))}. "
            "All editions of a Work must be in the same library."
        )
    return next(iter(library_ids)) if library_ids else None


async def assert_book_can_join_work(
    book_id: uuid.UUID, work_id: uuid.UUID, db: AsyncSession
) -> None:
    """Validate that adding `book_id` to `work_id` keeps the Work in a single
    library. If the Work has no books yet, only the new book's invariant is
    checked.
    """
    result = await db.execute(select(Book.id).where(Book.work_id == work_id).limit(1))
    existing_book_id = result.scalar_one_or_none()
    if existing_book_id is None:
        await assert_books_share_single_library([book_id], db)
        return
    await assert_books_share_single_library([existing_book_id, book_id], db)


async def book_is_in_work(book_id: uuid.UUID, db: AsyncSession) -> bool:
    result = await db.execute(select(Book.work_id).where(Book.id == book_id))
    work_id = result.scalar_one_or_none()
    return work_id is not None
