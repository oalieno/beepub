import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import coalesce
from sqlalchemy.types import String as SAString

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book
from app.models.library import Library, LibraryBook, UserLibraryExclusion
from app.models.tag import BookTag
from app.models.user import User, UserRole
from app.schemas.book import PaginatedBooks
from app.schemas.library import (
    LibraryBookAdd,
    LibraryCreate,
    LibraryListOut,
    LibraryOut,
    LibraryUpdate,
)

router = APIRouter(prefix="/api/libraries", tags=["libraries"])


def accessible_libraries_condition(user: User):
    if user.role == UserRole.admin:
        return True  # no filter
    return ~exists(
        select(UserLibraryExclusion.library_id).where(
            UserLibraryExclusion.user_id == user.id,
            UserLibraryExclusion.library_id == Library.id,
        )
    )


@router.get("", response_model=list[LibraryListOut])
async def list_libraries(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    query = select(Library)
    if current_user.role != UserRole.admin:
        query = query.where(accessible_libraries_condition(current_user))
    result = await db.execute(query.order_by(Library.created_at.desc()))
    libraries = result.scalars().all()

    if not libraries:
        return []

    library_ids = [lib.id for lib in libraries]

    # Batch query: book counts per library
    count_result = await db.execute(
        select(LibraryBook.library_id, func.count())
        .where(LibraryBook.library_id.in_(library_ids))
        .group_by(LibraryBook.library_id)
    )
    counts = dict(count_result.all())

    # Batch query: top 4 book IDs with covers per library

    ranked = (
        select(
            LibraryBook.library_id,
            LibraryBook.book_id,
            func.row_number()
            .over(
                partition_by=LibraryBook.library_id,
                order_by=LibraryBook.added_at.desc(),
            )
            .label("rn"),
        )
        .join(Book, Book.id == LibraryBook.book_id)
        .where(LibraryBook.library_id.in_(library_ids))
        .where(Book.cover_path.isnot(None))
        .subquery()
    )
    preview_result = await db.execute(
        select(ranked.c.library_id, ranked.c.book_id).where(ranked.c.rn <= 4)
    )
    previews: dict[str, list] = {}
    for lib_id, book_id in preview_result.all():
        previews.setdefault(lib_id, []).append(book_id)

    return [
        LibraryListOut(
            **{c.key: getattr(lib, c.key) for c in lib.__table__.columns},
            book_count=counts.get(lib.id, 0),
            preview_book_ids=previews.get(lib.id, []),
        )
        for lib in libraries
    ]


@router.post("", response_model=LibraryOut, status_code=status.HTTP_201_CREATED)
async def create_library(
    body: LibraryCreate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    library = Library(**body.model_dump(), created_by=current_user.id)
    db.add(library)
    await db.commit()
    await db.refresh(library)
    return library


@router.get("/{library_id}", response_model=LibraryOut)
async def get_library(
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    library = await _get_accessible_library(library_id, current_user, db)
    return library


@router.put("/{library_id}", response_model=LibraryOut)
async def update_library(
    library_id: uuid.UUID,
    body: LibraryUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(library, field, value)
    await db.commit()
    await db.refresh(library)
    return library


@router.delete("/{library_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library(
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    # Delete all books in this library (and their files)
    from app.services.storage import delete_file

    book_result = await db.execute(
        select(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(LibraryBook.library_id == library_id)
    )
    for book in book_result.scalars().all():
        # Only delete EPUB file for non-Calibre books (Calibre files are on read-only mount)
        if book.calibre_id is None:
            delete_file(book.file_path)
        if book.cover_path:
            delete_file(book.cover_path)
        await db.delete(book)

    await db.delete(library)
    await db.commit()


@router.get("/{library_id}/books", response_model=PaginatedBooks)
async def list_library_books(
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    series: str | None = Query(None),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    await _get_accessible_library(library_id, current_user, db)
    base_query = (
        select(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(LibraryBook.library_id == library_id)
    )
    if search:
        pattern = f"%{search}%"
        base_query = base_query.where(
            or_(
                Book.title.ilike(pattern),
                Book.epub_title.ilike(pattern),
                cast(Book.authors, SAString).ilike(pattern),
                cast(Book.epub_authors, SAString).ilike(pattern),
                Book.series.ilike(pattern),
                Book.epub_series.ilike(pattern),
                Book.epub_isbn.ilike(pattern),
            )
        )
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

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply sorting and pagination (secondary sort on id for deterministic offset/limit)
    sort_map = {
        "display_title": coalesce(Book.title, Book.epub_title),
        "added_at": coalesce(Book.calibre_added_at, Book.created_at),
        "series_index": coalesce(Book.series_index, Book.epub_series_index),
    }
    # Default to series_index sort when filtering by series
    if series and sort == "created_at":
        sort = "series_index"
        order = "asc"
    sort_col = sort_map.get(sort, getattr(Book, sort, Book.created_at))
    if sort == "series_index":
        # Sort by series name first, then index within each series; NULLS LAST
        series_col = coalesce(Book.series, Book.epub_series)
        if order == "desc":
            base_query = base_query.order_by(
                series_col.desc().nullslast(), sort_col.desc().nullslast(), Book.id
            )
        else:
            base_query = base_query.order_by(
                series_col.asc().nullslast(), sort_col.asc().nullslast(), Book.id
            )
    elif order == "desc":
        base_query = base_query.order_by(sort_col.desc(), Book.id)
    else:
        base_query = base_query.order_by(sort_col.asc(), Book.id)
    base_query = base_query.offset(offset).limit(limit)

    result = await db.execute(base_query)
    return PaginatedBooks(items=result.scalars().all(), total=total)


@router.post("/{library_id}/books", status_code=status.HTTP_201_CREATED)
async def add_book_to_library(
    library_id: uuid.UUID,
    body: LibraryBookAdd,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    if library.calibre_path:
        raise HTTPException(
            status_code=403, detail="Cannot add books to a Calibre library"
        )
    existing = await db.execute(
        select(LibraryBook).where(
            LibraryBook.library_id == library_id, LibraryBook.book_id == body.book_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Book already in library")
    lb = LibraryBook(
        library_id=library_id, book_id=body.book_id, added_by=current_user.id
    )
    db.add(lb)
    await db.commit()
    return {"status": "added"}


@router.delete("/{library_id}/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_book_from_library(
    library_id: uuid.UUID,
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(LibraryBook).where(
            LibraryBook.library_id == library_id, LibraryBook.book_id == book_id
        )
    )
    lb = result.scalar_one_or_none()
    if not lb:
        raise HTTPException(status_code=404, detail="Book not in library")
    await db.delete(lb)
    await db.commit()


async def _get_accessible_library(
    library_id: uuid.UUID, user: User, db: AsyncSession
) -> Library:
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    if user.role == UserRole.admin:
        return library
    # Check if user is excluded from this library
    exclusion = await db.execute(
        select(UserLibraryExclusion).where(
            UserLibraryExclusion.library_id == library_id,
            UserLibraryExclusion.user_id == user.id,
        )
    )
    if exclusion.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")
    return library
