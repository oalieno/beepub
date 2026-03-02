import uuid
import os
from datetime import datetime, timezone
from typing import Annotated, Optional
import zipfile
import mimetypes
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.database import get_db
from app.deps import get_current_user, get_current_user_or_cookie, require_admin
from app.models.user import User, UserRole
from app.models.book import Book, ExternalMetadata
from app.models.library import LibraryBook, LibraryAccess, Library, LibraryVisibility
from app.schemas.book import BookOut, BookMetadataUpdate, ExternalMetadataOut
from app.schemas.reading import RatingUpdate, FavoriteUpdate, ProgressUpdate, ProgressOut, HighlightCreate, HighlightUpdate, HighlightOut, InteractionOut
from app.models.reading import UserBookInteraction, Highlight
from app.services.storage import get_book_path, get_cover_path, save_upload_file, delete_file
from app.services.epub_parser import parse_epub_metadata, extract_cover
from app.services.metadata_queue import push_metadata_job
from app.config import settings

router = APIRouter(prefix="/api/books", tags=["books"])


async def _user_can_access_book(book_id: uuid.UUID, user: User, db: AsyncSession) -> bool:
    if user.role == UserRole.admin:
        return True
    # Check if book is in any accessible library
    result = await db.execute(
        select(LibraryBook)
        .join(Library, Library.id == LibraryBook.library_id)
        .where(
            LibraryBook.book_id == book_id,
            or_(
                Library.visibility == LibraryVisibility.public,
                Library.id.in_(
                    select(LibraryAccess.library_id).where(LibraryAccess.user_id == user.id)
                )
            )
        )
    )
    return result.scalar_one_or_none() is not None


@router.get("", response_model=list[BookOut])
async def search_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Optional[str] = Query(None),
):
    if current_user.role == UserRole.admin:
        query = select(Book)
    else:
        accessible_lib_ids = select(LibraryAccess.library_id).where(LibraryAccess.user_id == current_user.id)
        query = (
            select(Book)
            .join(LibraryBook, LibraryBook.book_id == Book.id)
            .join(Library, Library.id == LibraryBook.library_id)
            .where(
                or_(
                    Library.visibility == LibraryVisibility.public,
                    Library.id.in_(accessible_lib_ids)
                )
            )
            .distinct()
        )
    if q:
        query = query.where(
            or_(
                Book.title.ilike(f"%{q}%"),
                Book.epub_title.ilike(f"%{q}%"),
            )
        )
    result = await db.execute(query.order_by(Book.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def upload_book(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    library_id: Optional[str] = Form(None),
):
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Only EPUB files are supported")

    book_id = uuid.uuid4()
    file_path = get_book_path(book_id, file.filename)
    cover_path = get_cover_path(book_id)

    file_size = await save_upload_file(file, file_path)
    metadata = parse_epub_metadata(file_path)
    cover_ok = extract_cover(file_path, cover_path)

    book = Book(
        id=book_id,
        file_path=file_path,
        file_size=file_size,
        format="epub",
        cover_path=cover_path if cover_ok else None,
        added_by=current_user.id,
        **metadata,
    )
    db.add(book)
    await db.flush()

    if library_id:
        lib_id = uuid.UUID(library_id)
        lb = LibraryBook(library_id=lib_id, book_id=book_id, added_by=current_user.id)
        db.add(lb)

    await db.commit()
    await db.refresh(book)

    await push_metadata_job(book_id, priority="high")
    return book


@router.post("/bulk", response_model=list[BookOut], status_code=status.HTTP_201_CREATED)
async def upload_books_bulk(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    library_id: Optional[str] = Form(None),
):
    books = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".epub"):
            continue
        book_id = uuid.uuid4()
        file_path = get_book_path(book_id, file.filename)
        cover_path = get_cover_path(book_id)
        file_size = await save_upload_file(file, file_path)
        metadata = parse_epub_metadata(file_path)
        cover_ok = extract_cover(file_path, cover_path)
        book = Book(
            id=book_id,
            file_path=file_path,
            file_size=file_size,
            format="epub",
            cover_path=cover_path if cover_ok else None,
            added_by=current_user.id,
            **metadata,
        )
        db.add(book)
        await db.flush()
        if library_id:
            lb = LibraryBook(library_id=uuid.UUID(library_id), book_id=book_id, added_by=current_user.id)
            db.add(lb)
        books.append(book)
        await push_metadata_job(book_id, priority="normal")

    await db.commit()
    for book in books:
        await db.refresh(book)
    return books


@router.get("/{book_id}", response_model=BookOut)
async def get_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _get_book_with_access(book_id, current_user, db)
    return book


@router.put("/{book_id}/metadata", response_model=BookOut)
async def update_book_metadata(
    book_id: uuid.UUID,
    body: BookMetadataUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(book, field, value)
    await db.commit()
    await db.refresh(book)
    return book


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    delete_file(book.file_path)
    if book.cover_path:
        delete_file(book.cover_path)
    await db.delete(book)
    await db.commit()


@router.get("/{book_id}/file")
async def get_book_file(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _get_book_with_access(book_id, current_user, db)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(book.file_path, media_type="application/epub+zip")


@router.get("/{book_id}/content/{path:path}")
async def get_book_content(
    book_id: uuid.UUID,
    path: str,
    current_user: Annotated[User, Depends(get_current_user_or_cookie)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Serve individual files from within the EPUB zip (for epubjs reader)."""
    book = await _get_book_with_access(book_id, current_user, db)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with zipfile.ZipFile(book.file_path, "r") as zf:
            data = zf.read(path)
    except KeyError:
        raise HTTPException(status_code=404, detail="Path not found in EPUB")
    content_type, _ = mimetypes.guess_type(path)
    if content_type is None:
        content_type = "application/octet-stream"
    return Response(content=data, media_type=content_type)


@router.get("/{book_id}/cover")
async def get_book_cover(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _get_book_with_access(book_id, current_user, db)
    if not book.cover_path or not os.path.exists(book.cover_path):
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(book.cover_path, media_type="image/jpeg")


@router.post("/{book_id}/refresh")
async def refresh_book_metadata(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    await push_metadata_job(book_id, priority="high")
    return {"status": "queued"}


@router.get("/{book_id}/external", response_model=list[ExternalMetadataOut])
async def get_book_external_metadata(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(ExternalMetadata).where(ExternalMetadata.book_id == book_id)
    )
    return result.scalars().all()


# --- User Interactions ---

@router.get("/{book_id}/interaction", response_model=InteractionOut)
async def get_interaction(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id == book_id,
        )
    )
    interaction = result.scalar_one_or_none()
    if not interaction:
        return InteractionOut(rating=None, is_favorite=False, reading_progress=None, updated_at=datetime.now(timezone.utc))
    return interaction


@router.put("/{book_id}/rating")
async def update_rating(
    book_id: uuid.UUID,
    body: RatingUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be 1-5")
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.rating = body.rating
    await db.commit()
    return {"status": "updated"}


@router.put("/{book_id}/favorite")
async def update_favorite(
    book_id: uuid.UUID,
    body: FavoriteUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.is_favorite = body.is_favorite
    await db.commit()
    return {"status": "updated"}


@router.get("/{book_id}/progress", response_model=ProgressOut)
async def get_progress(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id == book_id,
        )
    )
    interaction = result.scalar_one_or_none()
    if not interaction or not interaction.reading_progress:
        return {}
    return interaction.reading_progress


@router.put("/{book_id}/progress")
async def update_progress(
    book_id: uuid.UUID,
    body: ProgressUpdate,
    current_user: Annotated[User, Depends(get_current_user_or_cookie)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import datetime, timezone
    await _get_book_with_access(book_id, current_user, db)
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    progress: dict = {
        "cfi": body.cfi,
        "percentage": body.percentage,
        "last_read_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.current_page is not None:
        progress["current_page"] = body.current_page
    if body.font_size is not None:
        progress["font_size"] = body.font_size
    if body.section_index is not None:
        progress["section_index"] = body.section_index
    if body.section_page is not None:
        progress["section_page"] = body.section_page
    if body.section_page_counts is not None:
        progress["section_page_counts"] = body.section_page_counts
    if body.total_pages is not None:
        progress["total_pages"] = body.total_pages
    interaction.reading_progress = progress
    await db.commit()
    return {"status": "updated"}


@router.get("/{book_id}/highlights", response_model=list[HighlightOut])
async def get_highlights(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(Highlight).where(
            Highlight.user_id == current_user.id,
            Highlight.book_id == book_id,
        ).order_by(Highlight.created_at.asc())
    )
    return result.scalars().all()


@router.post("/{book_id}/highlights", response_model=HighlightOut, status_code=status.HTTP_201_CREATED)
async def create_highlight(
    book_id: uuid.UUID,
    body: HighlightCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    highlight = Highlight(
        user_id=current_user.id,
        book_id=book_id,
        **body.model_dump(),
    )
    db.add(highlight)
    await db.commit()
    await db.refresh(highlight)
    return highlight


@router.put("/{book_id}/highlights/{highlight_id}", response_model=HighlightOut)
async def update_highlight(
    book_id: uuid.UUID,
    highlight_id: uuid.UUID,
    body: HighlightUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Highlight).where(
            Highlight.id == highlight_id,
            Highlight.user_id == current_user.id,
            Highlight.book_id == book_id,
        )
    )
    highlight = result.scalar_one_or_none()
    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(highlight, field, value)
    await db.commit()
    await db.refresh(highlight)
    return highlight


@router.delete("/{book_id}/highlights/{highlight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_highlight(
    book_id: uuid.UUID,
    highlight_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Highlight).where(
            Highlight.id == highlight_id,
            Highlight.user_id == current_user.id,
            Highlight.book_id == book_id,
        )
    )
    highlight = result.scalar_one_or_none()
    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")
    await db.delete(highlight)
    await db.commit()


async def _get_book_with_access(book_id: uuid.UUID, user: User, db: AsyncSession) -> Book:
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not await _user_can_access_book(book_id, user, db):
        raise HTTPException(status_code=403, detail="Access denied")
    return book


async def _get_or_create_interaction(
    user_id: uuid.UUID, book_id: uuid.UUID, db: AsyncSession
) -> UserBookInteraction:
    result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == user_id,
            UserBookInteraction.book_id == book_id,
        )
    )
    interaction = result.scalar_one_or_none()
    if not interaction:
        interaction = UserBookInteraction(user_id=user_id, book_id=book_id)
        db.add(interaction)
        await db.flush()
    return interaction
