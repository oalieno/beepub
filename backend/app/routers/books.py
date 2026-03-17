import mimetypes
import os
import re
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import coalesce

from app.database import get_db
from app.deps import get_current_user, get_current_user_or_cookie, require_admin
from app.models.book import Book, ExternalMetadata, MetadataSource
from app.models.library import Library, LibraryAccess, LibraryBook, LibraryVisibility
from app.models.reading import Highlight, ReadingActivity, UserBookInteraction
from app.models.user import User, UserRole
from app.schemas.book import (
    BookMetadataUpdate,
    BookOut,
    BookSearchResult,
    BookWithInteractionOut,
    ExternalMetadataOut,
    ExternalMetadataUrlUpdate,
    PaginatedBookSearchResults,
    PaginatedBooksWithInteraction,
)
from app.schemas.reading import (
    BatchInteractionItem,
    BatchInteractionRequest,
    BatchInteractionResponse,
    FavoriteUpdate,
    HighlightCreate,
    HighlightOut,
    HighlightUpdate,
    InteractionOut,
    NotesUpdate,
    ProgressOut,
    ProgressUpdate,
    RatingUpdate,
    ReadingActivityOut,
    ReadingStatusUpdate,
)
from app.services.epub_parser import extract_cover, parse_epub_metadata
from app.services.settings import get_setting
from app.services.storage import (
    delete_file,
    get_book_path,
    get_cover_path,
    save_upload_file,
)
from app.tasks.metadata import fetch_metadata
from app.tasks.wordcount import compute_word_count

router = APIRouter(prefix="/api/books", tags=["books"])


async def _user_can_access_book(
    book_id: uuid.UUID, user: User, db: AsyncSession
) -> bool:
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
                    select(LibraryAccess.library_id).where(
                        LibraryAccess.user_id == user.id
                    )
                ),
            ),
        )
    )
    return result.scalar_one_or_none() is not None


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def upload_book(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    library_id: str | None = Form(None),
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
        # Prevent uploading to Calibre libraries
        lib_result = await db.execute(select(Library).where(Library.id == lib_id))
        lib = lib_result.scalar_one_or_none()
        if lib and lib.calibre_path:
            raise HTTPException(status_code=403, detail="Cannot upload to a Calibre library")
        lb = LibraryBook(library_id=lib_id, book_id=book_id, added_by=current_user.id)
        db.add(lb)

    await db.commit()
    await db.refresh(book)

    fetch_metadata.delay(str(book_id))
    compute_word_count.delay(str(book_id))
    return book


@router.post("/bulk", response_model=list[BookOut], status_code=status.HTTP_201_CREATED)
async def upload_books_bulk(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    library_id: str | None = Form(None),
):
    # Prevent uploading to Calibre libraries
    if library_id:
        lib_result = await db.execute(
            select(Library).where(Library.id == uuid.UUID(library_id))
        )
        lib = lib_result.scalar_one_or_none()
        if lib and lib.calibre_path:
            raise HTTPException(status_code=403, detail="Cannot upload to a Calibre library")

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
            lb = LibraryBook(
                library_id=uuid.UUID(library_id),
                book_id=book_id,
                added_by=current_user.id,
            )
            db.add(lb)
        books.append(book)
        fetch_metadata.delay(str(book_id))
        compute_word_count.delay(str(book_id))

    await db.commit()
    for book in books:
        await db.refresh(book)
    return books


@router.get("/reading-activity", response_model=list[ReadingActivityOut])
async def get_reading_activity(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    year: int = Query(None),
):
    from datetime import date as date_type

    if year is None:
        year = date_type.today().year
    from sqlalchemy import extract

    result = await db.execute(
        select(ReadingActivity)
        .where(
            ReadingActivity.user_id == current_user.id,
            extract("year", ReadingActivity.date) == year,
        )
        .order_by(ReadingActivity.date)
    )
    return result.scalars().all()


@router.get("/me", response_model=PaginatedBooksWithInteraction)
async def list_my_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    reading_status: str | None = Query(None, alias="status"),
    favorite: bool | None = Query(None),
    sort: str = Query("last_read_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    from app.routers.libraries import accessible_libraries_condition

    # Subquery: book IDs the user can access (deduplicated)
    accessible_books = (
        select(LibraryBook.book_id)
        .join(Library, Library.id == LibraryBook.library_id)
    )
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_books = accessible_books.where(cond)
    accessible_book_ids = accessible_books.subquery()

    # Main query: join Book + UserBookInteraction, filter by accessible books
    base_query = (
        select(Book, UserBookInteraction)
        .join(UserBookInteraction, UserBookInteraction.book_id == Book.id)
        .where(
            UserBookInteraction.user_id == current_user.id,
            Book.id.in_(select(accessible_book_ids.c.book_id)),
        )
    )

    if reading_status is not None:
        base_query = base_query.where(
            UserBookInteraction.reading_status == reading_status
        )
    if favorite is not None:
        base_query = base_query.where(UserBookInteraction.is_favorite == favorite)

    # Count
    count_sub = base_query.with_only_columns(Book.id).subquery()
    count_query = select(func.count()).select_from(count_sub)
    total = (await db.execute(count_query)).scalar() or 0

    # Sorting
    last_read_col = UserBookInteraction.reading_progress["last_read_at"].astext
    sort_map = {
        "last_read_at": last_read_col,
        "updated_at": UserBookInteraction.updated_at,
        "display_title": coalesce(Book.title, Book.epub_title),
    }
    sort_col = sort_map.get(sort, last_read_col)
    if order == "desc":
        base_query = base_query.order_by(sort_col.desc(), Book.id)
    else:
        base_query = base_query.order_by(sort_col.asc(), Book.id)

    base_query = base_query.offset(offset).limit(limit)
    result = await db.execute(base_query)
    rows = result.all()

    items = []
    for book, interaction in rows:
        progress = interaction.reading_progress or {}
        item = BookWithInteractionOut.model_validate(book)
        item.reading_status = interaction.reading_status
        item.is_favorite = interaction.is_favorite
        item.reading_percentage = progress.get("percentage")
        item.last_read_at = progress.get("last_read_at")
        items.append(item)

    return PaginatedBooksWithInteraction(items=items, total=total)


@router.get("/random", response_model=list[BookOut])
async def get_random_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    count: int = Query(8, ge=1, le=20),
):
    from app.routers.libraries import accessible_libraries_condition

    accessible_books = select(LibraryBook.book_id).join(
        Library, Library.id == LibraryBook.library_id
    )
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_books = accessible_books.where(cond)
    accessible_book_ids = accessible_books.subquery()

    result = await db.execute(
        select(Book)
        .where(
            Book.id.in_(select(accessible_book_ids.c.book_id)),
            Book.cover_path.isnot(None),
        )
        .order_by(func.random())
        .limit(count)
    )
    books = result.scalars().all()
    if not books:
        raise HTTPException(status_code=404, detail="No accessible books found")
    return books


@router.post("/interactions/batch", response_model=BatchInteractionResponse)
async def batch_get_interactions(
    body: BatchInteractionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book_ids = body.book_ids[:200]
    if not book_ids:
        return BatchInteractionResponse(interactions={})
    result = await db.execute(
        select(UserBookInteraction.book_id, UserBookInteraction.reading_status).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id.in_(book_ids),
        )
    )
    interactions = {}
    for book_id, reading_status in result.all():
        interactions[str(book_id)] = BatchInteractionItem(reading_status=reading_status)
    return BatchInteractionResponse(interactions=interactions)


@router.get("/search", response_model=PaginatedBookSearchResults)
async def search_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query("", min_length=1),
    limit: int = Query(20, ge=1, le=100),
):
    from sqlalchemy import String as SAString
    from sqlalchemy import cast

    from app.routers.libraries import accessible_libraries_condition

    pattern = f"%{q}%"
    # Subquery: accessible library IDs
    accessible_libs = select(Library.id)
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_libs = accessible_libs.where(cond)
    accessible_lib_ids = accessible_libs.subquery()

    # Main query: search books in accessible libraries
    base_query = (
        select(Book, Library.name.label("library_name"))
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .join(Library, Library.id == LibraryBook.library_id)
        .where(
            LibraryBook.library_id.in_(select(accessible_lib_ids.c.id)),
            or_(
                Book.title.ilike(pattern),
                Book.epub_title.ilike(pattern),
                cast(Book.authors, SAString).ilike(pattern),
                cast(Book.epub_authors, SAString).ilike(pattern),
            ),
        )
        .distinct(Book.id)
        .order_by(Book.id, Library.name)
    )

    # Count
    count_sub = base_query.with_only_columns(Book.id).subquery()
    total = (await db.execute(select(func.count()).select_from(count_sub))).scalar() or 0

    result = await db.execute(base_query.limit(limit))
    items = []
    for book, library_name in result.all():
        item = BookSearchResult.model_validate(book)
        item.library_name = library_name
        items.append(item)

    return PaginatedBookSearchResults(items=items, total=total)


@router.get("/{book_id}", response_model=BookOut)
async def get_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _get_book_with_access(book_id, current_user, db)
    # Find the first library this book belongs to
    lb_result = await db.execute(
        select(LibraryBook.library_id)
        .where(LibraryBook.book_id == book_id)
        .limit(1)
    )
    library_id = lb_result.scalar_one_or_none()
    out = BookOut.model_validate(book)
    out.library_id = library_id
    return out


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
    data = body.model_dump()
    for field in body.model_fields_set:
        setattr(book, field, data[field])
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
    # Only delete the EPUB file for non-Calibre books (Calibre files are on read-only mount)
    if book.calibre_id is None:
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
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


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
    fetch_metadata.delay(str(book_id))
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


@router.put(
    "/{book_id}/external/{source}/url", response_model=ExternalMetadataOut
)
async def update_external_metadata_url(
    book_id: uuid.UUID,
    source: str,
    body: ExternalMetadataUrlUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Validate source
    try:
        validated_source = MetadataSource(source)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid source. Must be one of: "
            f"{', '.join(s.value for s in MetadataSource)}",
        )

    # Validate source URL format
    _SOURCE_URL_PATTERNS: dict[MetadataSource, re.Pattern[str]] = {
        MetadataSource.goodreads: re.compile(
            r"^https://www\.goodreads\.com/book/show/\d+[\w-]*$"
        ),
        MetadataSource.readmoo: re.compile(
            r"^https://readmoo\.com/book/\d+$"
        ),
    }
    if body.source_url is not None:
        pattern = _SOURCE_URL_PATTERNS.get(validated_source)
        if pattern and not pattern.match(body.source_url):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid URL format for {source}",
            )

    # Check book exists
    result = await db.execute(select(Book).where(Book.id == book_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Book not found")

    if body.source_url is None:
        # Delete the external metadata row for this source
        result = await db.execute(
            select(ExternalMetadata).where(
                ExternalMetadata.book_id == book_id,
                ExternalMetadata.source == validated_source,
            )
        )
        meta = result.scalar_one_or_none()
        if not meta:
            raise HTTPException(status_code=404, detail="External metadata not found")
        await db.delete(meta)
        await db.commit()
        return meta
    else:
        # Upsert: update existing or create new row with just the URL
        result = await db.execute(
            select(ExternalMetadata).where(
                ExternalMetadata.book_id == book_id,
                ExternalMetadata.source == validated_source,
            )
        )
        meta = result.scalar_one_or_none()
        if meta:
            meta.source_url = body.source_url
        else:
            meta = ExternalMetadata(
                book_id=book_id,
                source=validated_source,
                source_url=body.source_url,
            )
            db.add(meta)
        await db.commit()
        await db.refresh(meta)
        # Auto-trigger metadata refresh to fetch from the new URL
        fetch_metadata.delay(str(book_id))
        return meta


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
        return InteractionOut(
            rating=None,
            is_favorite=False,
            reading_progress=None,
            reading_status=None,
            started_at=None,
            finished_at=None,
            notes=None,
            updated_at=datetime.now(UTC),
        )
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


@router.put("/{book_id}/reading-status")
async def update_reading_status(
    book_id: uuid.UUID,
    body: ReadingStatusUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.reading import ReadingStatus

    await _get_book_with_access(book_id, current_user, db)
    if body.reading_status is not None:
        valid = {s.value for s in ReadingStatus}
        if body.reading_status not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reading status. Must be one of: {', '.join(valid)}",
            )
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.reading_status = body.reading_status
    interaction.started_at = body.started_at
    interaction.finished_at = body.finished_at
    await db.commit()
    return {"status": "updated"}


@router.put("/{book_id}/notes")
async def update_notes(
    book_id: uuid.UUID,
    body: NotesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)
    interaction.notes = body.notes
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
    await _get_book_with_access(book_id, current_user, db)
    interaction = await _get_or_create_interaction(current_user.id, book_id, db)

    now = datetime.now(UTC)
    # Track reading minutes from time delta (only when triggered by user action)
    if body.track_activity:
        old_last_read = None
        if interaction.reading_progress and interaction.reading_progress.get(
            "last_read_at"
        ):
            try:
                old_last_read = datetime.fromisoformat(
                    interaction.reading_progress["last_read_at"]
                )
            except (ValueError, TypeError):
                pass
        if old_last_read:
            delta = (now - old_last_read).total_seconds()
            if 0 < delta < 300:  # < 5 minutes = same session
                delta_seconds = int(delta)
                tz_name = await get_setting(db, "timezone")
                today = datetime.now(ZoneInfo(tz_name)).date()
                result = await db.execute(
                    select(ReadingActivity).where(
                        ReadingActivity.user_id == current_user.id,
                        ReadingActivity.date == today,
                    )
                )
                activity = result.scalar_one_or_none()
                if activity:
                    activity.seconds = activity.seconds + delta_seconds
                else:
                    db.add(
                        ReadingActivity(
                            user_id=current_user.id,
                            date=today,
                            seconds=delta_seconds,
                        )
                    )

    progress: dict = {
        "cfi": body.cfi,
        "percentage": body.percentage,
        "last_read_at": now.isoformat(),
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
        select(Highlight)
        .where(
            Highlight.user_id == current_user.id,
            Highlight.book_id == book_id,
        )
        .order_by(Highlight.created_at.asc())
    )
    return result.scalars().all()


@router.post(
    "/{book_id}/highlights",
    response_model=HighlightOut,
    status_code=status.HTTP_201_CREATED,
)
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


@router.delete(
    "/{book_id}/highlights/{highlight_id}", status_code=status.HTTP_204_NO_CONTENT
)
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


async def _get_book_with_access(
    book_id: uuid.UUID, user: User, db: AsyncSession
) -> Book:
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
