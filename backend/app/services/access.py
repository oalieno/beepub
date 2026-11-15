"""Which libraries and books a user may see.

The one place the rule is written. Every way into the data — the web
API, OPDS, kosync, MCP, device sync — asks here, so a new one cannot
get it subtly different.

The rule: an admin sees everything. Anyone else sees every library they
have not been excluded from (``user_library_exclusions``), and a book
when it is in at least one such library.
"""

import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import errors
from app.models.book import Book
from app.models.library import Library, LibraryBook, UserLibraryExclusion
from app.models.user import User, UserRole


def accessible_libraries_condition(user: User):
    """A WHERE condition on ``Library`` rows the user may see — or
    ``True`` for an admin, who needs no filter."""
    if user.role == UserRole.admin:
        return True
    return ~exists(
        select(UserLibraryExclusion.library_id).where(
            UserLibraryExclusion.user_id == user.id,
            UserLibraryExclusion.library_id == Library.id,
        )
    )


def accessible_book_ids_select(user: User):
    """SELECT of the ids of the books the user may see.

    Every list and search builds on this instead of writing the
    exclusion filter again.
    """
    stmt = select(LibraryBook.book_id).join(
        Library, Library.id == LibraryBook.library_id
    )
    cond = accessible_libraries_condition(user)
    if cond is not True:
        stmt = stmt.where(cond)
    return stmt


async def get_accessible_library(
    library_id: uuid.UUID, user: User, db: AsyncSession
) -> Library:
    """The library, or 404 when there is none and 403 when it is not
    the user's to see."""
    library = (
        await db.execute(select(Library).where(Library.id == library_id))
    ).scalar_one_or_none()
    if not library:
        raise errors.LIBRARY_NOT_FOUND()
    if user.role == UserRole.admin:
        return library
    excluded = await db.scalar(
        select(
            exists().where(
                UserLibraryExclusion.library_id == library_id,
                UserLibraryExclusion.user_id == user.id,
            )
        )
    )
    if excluded:
        raise errors.ACCESS_DENIED()
    return library


async def can_access_book(book_id: uuid.UUID, user: User, db: AsyncSession) -> bool:
    if user.role == UserRole.admin:
        return True
    # (EXISTS, not a fetched row: a book can be in several libraries.)
    return bool(
        await db.scalar(
            select(
                accessible_book_ids_select(user)
                .where(LibraryBook.book_id == book_id)
                .exists()
            )
        )
    )


async def get_accessible_book(book_id: uuid.UUID, user: User, db: AsyncSession) -> Book:
    """The book, or 404 when there is none and 403 when it is not the
    user's to see."""
    book = (
        await db.execute(select(Book).where(Book.id == book_id))
    ).scalar_one_or_none()
    if not book:
        raise errors.BOOK_NOT_FOUND()
    if not await can_access_book(book_id, user, db):
        raise errors.ACCESS_DENIED()
    return book
