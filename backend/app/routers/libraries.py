import uuid
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func, case
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.user import User, UserRole
from app.models.library import Library, LibraryAccess, LibraryBook, LibraryVisibility
from app.models.book import Book
from app.schemas.library import LibraryCreate, LibraryUpdate, LibraryOut, LibraryListOut, LibraryMemberAdd, LibraryMemberOut, LibraryBookAdd
from app.schemas.book import BookOut

router = APIRouter(prefix="/api/libraries", tags=["libraries"])


def accessible_libraries_condition(user: User):
    if user.role == UserRole.admin:
        return True  # no filter
    return or_(
        Library.visibility == LibraryVisibility.public,
        and_(
            Library.visibility == LibraryVisibility.private,
            Library.id.in_(
                select(LibraryAccess.library_id).where(LibraryAccess.user_id == user.id)
            )
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
    from sqlalchemy import literal_column
    ranked = (
        select(
            LibraryBook.library_id,
            LibraryBook.book_id,
            func.row_number().over(
                partition_by=LibraryBook.library_id,
                order_by=LibraryBook.added_at.desc()
            ).label("rn")
        )
        .join(Book, Book.id == LibraryBook.book_id)
        .where(LibraryBook.library_id.in_(library_ids))
        .where(Book.cover_path.isnot(None))
        .subquery()
    )
    preview_result = await db.execute(
        select(ranked.c.library_id, ranked.c.book_id)
        .where(ranked.c.rn <= 4)
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
    await db.delete(library)
    await db.commit()


@router.get("/{library_id}/books", response_model=list[BookOut])
async def list_library_books(
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: Optional[str] = Query(None),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
):
    await _get_accessible_library(library_id, current_user, db)
    query = (
        select(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(LibraryBook.library_id == library_id)
    )
    if search:
        query = query.where(
            or_(
                Book.title.ilike(f"%{search}%"),
                Book.epub_title.ilike(f"%{search}%"),
            )
        )
    sort_col = getattr(Book, sort, Book.created_at)
    if order == "desc":
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{library_id}/books", status_code=status.HTTP_201_CREATED)
async def add_book_to_library(
    library_id: uuid.UUID,
    body: LibraryBookAdd,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Library).where(Library.id == library_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Library not found")
    existing = await db.execute(
        select(LibraryBook).where(
            LibraryBook.library_id == library_id, LibraryBook.book_id == body.book_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Book already in library")
    lb = LibraryBook(library_id=library_id, book_id=body.book_id, added_by=current_user.id)
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


@router.get("/{library_id}/members", response_model=list[LibraryMemberOut])
async def list_library_members(
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(LibraryAccess).where(LibraryAccess.library_id == library_id)
    )
    return result.scalars().all()


@router.post("/{library_id}/members", status_code=status.HTTP_201_CREATED)
async def add_library_member(
    library_id: uuid.UUID,
    body: LibraryMemberAdd,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await db.execute(
        select(LibraryAccess).where(
            LibraryAccess.library_id == library_id, LibraryAccess.user_id == body.user_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already has access")
    access = LibraryAccess(
        library_id=library_id,
        user_id=body.user_id,
        granted_by=current_user.id,
    )
    db.add(access)
    await db.commit()
    return {"status": "granted"}


@router.delete("/{library_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_library_member(
    library_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(LibraryAccess).where(
            LibraryAccess.library_id == library_id, LibraryAccess.user_id == user_id
        )
    )
    access = result.scalar_one_or_none()
    if not access:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(access)
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
    if library.visibility == LibraryVisibility.public:
        return library
    access = await db.execute(
        select(LibraryAccess).where(
            LibraryAccess.library_id == library_id,
            LibraryAccess.user_id == user.id,
        )
    )
    if not access.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")
    return library
