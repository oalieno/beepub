"""Work management endpoints — group book editions into logical works."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import require_admin
from app.models.book import Book
from app.models.user import User
from app.models.work import Work
from app.schemas.work import (
    DuplicateSuggestionsOut,
    WorkCreate,
    WorkOut,
    WorkUpdate,
)

router = APIRouter(prefix="/api/works", tags=["works"])


def _work_to_out(work: Work) -> WorkOut:
    """Convert Work model to WorkOut schema."""
    return WorkOut(
        id=work.id,
        title=work.title,
        authors=work.authors,
        primary_book_id=work.primary_book_id,
        books=[
            {
                "id": b.id,
                "display_title": b.display_title,
                "display_authors": b.display_authors,
                "cover_path": b.cover_path,
                "epub_isbn": b.epub_isbn,
                "metadata_count": b.metadata_count,
                "created_at": b.created_at,
            }
            for b in work.books
        ],
        created_at=work.created_at,
    )


@router.post("", response_model=WorkOut, status_code=status.HTTP_201_CREATED)
async def create_work(
    body: WorkCreate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Merge books into a Work. Auto-picks primary by newest created_at."""
    # Fetch all books
    result = await db.execute(
        select(Book).where(Book.id.in_(body.book_ids)).order_by(Book.created_at.desc())
    )
    books = list(result.scalars().all())

    if len(books) != len(body.book_ids):
        found_ids = {b.id for b in books}
        missing = [str(bid) for bid in body.book_ids if bid not in found_ids]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Books not found: {', '.join(missing)}",
        )

    # Check if any book is already in a Work
    for book in books:
        if book.work_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Book '{book.display_title}' (id={book.id}) is already in a Work",
            )

    # Use the newest book as primary, derive canonical metadata
    primary = books[0]  # already sorted by created_at DESC
    work = Work(
        title=primary.display_title or "Untitled Work",
        authors=primary.display_authors,
    )
    db.add(work)
    await db.flush()  # get work.id

    # Link books
    for book in books:
        book.work_id = work.id

    # Set primary (post_update handles the circular FK)
    work.primary_book_id = primary.id
    await db.commit()

    # Reload with books relationship
    result = await db.execute(
        select(Work).where(Work.id == work.id).options(selectinload(Work.books))
    )
    work = result.scalar_one()
    return _work_to_out(work)


@router.get("/suggestions", response_model=DuplicateSuggestionsOut)
async def get_suggestions(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Scan library for potential duplicate edition groups (exact match only)."""
    from app.services.work_matching import find_duplicate_groups

    groups, total_scanned, truncated = await find_duplicate_groups(db)

    # Filter out groups containing excluded book pairs
    from app.models.work import WorkScanExclusion

    excl_result = await db.execute(
        select(WorkScanExclusion.book_id_a, WorkScanExclusion.book_id_b)
    )
    excluded_pairs = {(min(r[0], r[1]), max(r[0], r[1])) for r in excl_result.all()}

    if excluded_pairs:
        filtered_groups = []
        for g in groups:
            book_ids = [b["id"] for b in g["books"]]
            has_exclusion = False
            for i, a in enumerate(book_ids):
                for b in book_ids[i + 1 :]:
                    pair = (min(a, b), max(a, b))
                    if pair in excluded_pairs:
                        has_exclusion = True
                        break
                if has_exclusion:
                    break
            if not has_exclusion:
                filtered_groups.append(g)
        groups = filtered_groups

    return DuplicateSuggestionsOut(
        groups=groups,
        total_books_scanned=total_scanned,
        truncated=truncated,
    )


@router.post("/exclusions", status_code=status.HTTP_201_CREATED)
async def create_exclusion(
    body: dict,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mark a group of books as 'not duplicates'. Stores all C(N,2) pairs."""
    from app.models.work import WorkScanExclusion

    book_ids = body.get("book_ids", [])
    if len(book_ids) < 2:
        raise HTTPException(status_code=422, detail="At least 2 book IDs required")

    # Insert all pairs (smaller ID first for consistency)
    import uuid as uuid_mod

    parsed_ids = [uuid_mod.UUID(str(bid)) for bid in book_ids]
    for i, a in enumerate(parsed_ids):
        for b in parsed_ids[i + 1 :]:
            pair_a, pair_b = (min(a, b), max(a, b))
            # Upsert: skip if pair already exists
            existing = await db.execute(
                select(WorkScanExclusion).where(
                    WorkScanExclusion.book_id_a == pair_a,
                    WorkScanExclusion.book_id_b == pair_b,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(WorkScanExclusion(book_id_a=pair_a, book_id_b=pair_b))

    await db.commit()
    return {"status": "excluded", "pairs": len(parsed_ids) * (len(parsed_ids) - 1) // 2}


@router.get("/{work_id}", response_model=WorkOut)
async def get_work(
    work_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a Work with all its editions."""
    result = await db.execute(
        select(Work).where(Work.id == work_id).options(selectinload(Work.books))
    )
    work = result.scalar_one_or_none()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    return _work_to_out(work)


@router.patch("/{work_id}", response_model=WorkOut)
async def update_work(
    work_id: uuid.UUID,
    body: WorkUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a Work's canonical metadata or primary edition."""
    result = await db.execute(
        select(Work).where(Work.id == work_id).options(selectinload(Work.books))
    )
    work = result.scalar_one_or_none()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    if body.title is not None:
        work.title = body.title
    if body.authors is not None:
        work.authors = body.authors
    if body.primary_book_id is not None:
        # Verify the book belongs to this Work
        book_ids = {b.id for b in work.books}
        if body.primary_book_id not in book_ids:
            raise HTTPException(
                status_code=400,
                detail="primary_book_id must be an edition in this Work",
            )
        work.primary_book_id = body.primary_book_id

    await db.commit()
    await db.refresh(work)
    return _work_to_out(work)


@router.delete("/{work_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work(
    work_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a Work. Books get work_id = NULL (via DB ON DELETE SET NULL)."""
    result = await db.execute(select(Work).where(Work.id == work_id))
    work = result.scalar_one_or_none()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    await db.delete(work)
    await db.commit()


@router.post(
    "/{work_id}/books/{book_id}",
    response_model=WorkOut,
    status_code=status.HTTP_200_OK,
)
async def add_book_to_work(
    work_id: uuid.UUID,
    book_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a book to an existing Work."""
    result = await db.execute(
        select(Work).where(Work.id == work_id).options(selectinload(Work.books))
    )
    work = result.scalar_one_or_none()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.work_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Book is already in a Work (work_id={book.work_id})",
        )

    book.work_id = work.id
    await db.commit()

    # Reload
    result = await db.execute(
        select(Work).where(Work.id == work_id).options(selectinload(Work.books))
    )
    work = result.scalar_one()
    return _work_to_out(work)


@router.delete(
    "/{work_id}/books/{book_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_book_from_work(
    work_id: uuid.UUID,
    book_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a book from a Work. If last book, auto-deletes the Work."""
    result = await db.execute(
        select(Work).where(Work.id == work_id).options(selectinload(Work.books))
    )
    work = result.scalar_one_or_none()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    target_book = None
    for b in work.books:
        if b.id == book_id:
            target_book = b
            break

    if not target_book:
        raise HTTPException(status_code=404, detail="Book not found in this Work")

    # Unlink the book
    target_book.work_id = None

    remaining = [b for b in work.books if b.id != book_id]

    if not remaining:
        # Last book removed — auto-delete the Work
        await db.delete(work)
    else:
        # If removed book was the primary, promote the newest remaining
        if work.primary_book_id == book_id:
            newest = max(remaining, key=lambda b: b.created_at)
            work.primary_book_id = newest.id

    await db.commit()
