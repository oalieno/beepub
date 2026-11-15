import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book
from app.models.library import Library, LibraryBook
from app.models.user import User, UserRole
from app.schemas.library import (
    LibraryCreate,
    LibraryListOut,
    LibraryOut,
    LibraryUpdate,
)
from app.services.access import accessible_libraries_condition, get_accessible_library

router = APIRouter(prefix="/api/libraries", tags=["libraries"])


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

    # For each library its four newest (LATERAL: one short walk of the
    # library's own index, not a ranking of every book in all of them).
    newest = (
        select(LibraryBook.book_id)
        .join(Book, Book.id == LibraryBook.book_id)
        .where(
            LibraryBook.library_id == Library.id,
            Book.cover_path.isnot(None),
        )
        .order_by(LibraryBook.added_at.desc())
        .limit(4)
        .lateral()
    )
    preview_result = await db.execute(
        select(Library.id, newest.c.book_id)
        .select_from(Library)
        .join(newest, true())
        .where(Library.id.in_(library_ids))
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
    library = await get_accessible_library(library_id, current_user, db)
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

    # Delete all books in this library (and their files). Files are removed
    # AFTER the commit — a failed commit must not leave rows pointing at
    # already-deleted files.
    from app.services.book_files import book_files
    from app.services.storage import delete_file

    book_result = await db.execute(
        select(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(LibraryBook.library_id == library_id)
    )
    paths: list[str] = []
    work_ids: set[uuid.UUID] = set()
    for book in book_result.scalars().all():
        paths.extend(book_files(book))
        if book.work_id:
            work_ids.add(book.work_id)
        await db.delete(book)

    if work_ids:
        from app.services.work_library import cleanup_orphan_works

        await cleanup_orphan_works(db, list(work_ids))

    await db.delete(library)
    await db.commit()
    for path in paths:
        delete_file(path)
