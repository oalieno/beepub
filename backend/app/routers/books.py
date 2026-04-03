import mimetypes
import os
import re
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
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
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import coalesce

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book, ExternalMetadata, MetadataSource
from app.models.library import Library, LibraryBook, UserLibraryExclusion
from app.models.reading import Highlight, ReadingActivity, UserBookInteraction
from app.models.tag import BookTag
from app.models.user import User, UserRole
from app.schemas.book import (
    BookMetadataUpdate,
    BookOut,
    BookReportCreate,
    BookReportOut,
    BookSearchResult,
    BookWithInteractionOut,
    ExternalMetadataOut,
    ExternalMetadataUrlUpdate,
    PaginatedBooks,
    PaginatedBookSearchResults,
    PaginatedBooksWithInteraction,
    SeriesBookBrief,
    SeriesNeighborsOut,
    SeriesProgress,
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
    ReadingGoalUpdate,
    ReadingStatsOut,
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
from app.tasks.auto_tag import auto_tag_book
from app.tasks.metadata import fetch_metadata
from app.tasks.text_extract import extract_book_text

router = APIRouter(prefix="/api/books", tags=["books"])


async def _user_can_access_book(
    book_id: uuid.UUID, user: User, db: AsyncSession
) -> bool:
    if user.role == UserRole.admin:
        return True
    # Check if book is in any non-excluded library
    result = await db.execute(
        select(LibraryBook)
        .join(Library, Library.id == LibraryBook.library_id)
        .where(
            LibraryBook.book_id == book_id,
            ~exists(
                select(UserLibraryExclusion.library_id).where(
                    UserLibraryExclusion.user_id == user.id,
                    UserLibraryExclusion.library_id == Library.id,
                )
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
            raise HTTPException(
                status_code=403, detail="Cannot upload to a Calibre library"
            )
        lb = LibraryBook(library_id=lib_id, book_id=book_id, added_by=current_user.id)
        db.add(lb)

    await db.commit()
    await db.refresh(book)

    fetch_metadata.apply_async(args=[str(book_id)], link=auto_tag_book.si(str(book_id)))
    extract_book_text.delay(str(book_id))
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
            raise HTTPException(
                status_code=403, detail="Cannot upload to a Calibre library"
            )

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
        fetch_metadata.apply_async(
            args=[str(book_id)], link=auto_tag_book.si(str(book_id))
        )
        extract_book_text.delay(str(book_id))

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


@router.get("/reading-stats", response_model=ReadingStatsOut)
async def get_reading_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get reading streak and goal progress for the current user."""
    tz_name = await get_setting(db, "timezone")
    try:
        today = datetime.now(ZoneInfo(tz_name)).date()
    except (KeyError, Exception):
        today = datetime.now(UTC).date()

    # Fetch all reading days ordered by date desc
    result = await db.execute(
        select(ReadingActivity.date, ReadingActivity.seconds)
        .where(
            ReadingActivity.user_id == current_user.id,
            ReadingActivity.seconds > 0,
        )
        .order_by(ReadingActivity.date.desc())
    )
    rows = result.all()

    today_seconds = 0
    dates_with_reading: list[date] = []
    for row in rows:
        if row.date == today:
            today_seconds = row.seconds
        dates_with_reading.append(row.date)

    # Compute current streak (Duolingo-style: grace if not read today yet)
    current_streak = _compute_streak(dates_with_reading, today)

    # Compute longest streak
    longest_streak = _compute_longest_streak(dates_with_reading)

    return ReadingStatsOut(
        current_streak=current_streak,
        longest_streak=max(longest_streak, current_streak),
        today_seconds=today_seconds,
        goal_seconds=current_user.daily_reading_goal_seconds,
    )


def _compute_streak(dates: list[date], today: date) -> int:
    """Count consecutive days with reading, starting from today or yesterday."""
    if not dates:
        return 0

    # Start from today; if no reading today, try yesterday (grace period)
    expected = today
    if dates[0] != today:
        expected = today - timedelta(days=1)

    streak = 0
    for d in dates:
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    return streak


def _compute_longest_streak(dates: list[date]) -> int:
    """Find the longest consecutive run in a desc-sorted list of dates."""
    if not dates:
        return 0

    longest = 1
    current = 1
    for i in range(1, len(dates)):
        if dates[i] == dates[i - 1] - timedelta(days=1):
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


@router.put("/reading-goal", response_model=ReadingStatsOut)
async def update_reading_goal(
    body: ReadingGoalUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set, update, or remove the daily reading goal."""
    if body.goal_seconds is not None and (
        body.goal_seconds < 60 or body.goal_seconds > 86400
    ):
        raise HTTPException(
            status_code=422,
            detail="Goal must be between 60 and 86400 seconds (1 min to 24 hrs)",
        )

    current_user.daily_reading_goal_seconds = body.goal_seconds
    await db.commit()

    # Return updated stats
    return await get_reading_stats(current_user, db)


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
    accessible_books = select(LibraryBook.book_id).join(
        Library, Library.id == LibraryBook.library_id
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
                Book.series.ilike(pattern),
                Book.epub_series.ilike(pattern),
            ),
        )
        .distinct(Book.id)
        .order_by(Book.id, Library.name)
    )

    # Count
    count_sub = base_query.with_only_columns(Book.id).subquery()
    total = (
        await db.execute(select(func.count()).select_from(count_sub))
    ).scalar() or 0

    result = await db.execute(base_query.limit(limit))
    items = []
    for book, library_name in result.all():
        item = BookSearchResult.model_validate(book)
        item.library_name = library_name
        items.append(item)

    return PaginatedBookSearchResults(items=items, total=total)


@router.get("/discover/recommendations", response_model=list[BookWithInteractionOut])
async def get_discover_recommendations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=50),
):
    """Personalized book recommendations based on reading history."""
    from app.services.recommendations import get_personalized_recommendations

    recs = await get_personalized_recommendations(
        db,
        current_user.id,
        is_admin=current_user.role == UserRole.admin,
        limit=limit,
    )
    if not recs:
        return []

    book_ids = [r["book_id"] for r in recs]

    result = await db.execute(select(Book).where(Book.id.in_(book_ids)))
    books = {b.id: b for b in result.scalars().all()}

    # Get interactions
    interaction_result = await db.execute(
        select(UserBookInteraction).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id.in_(book_ids),
        )
    )
    interactions = {i.book_id: i for i in interaction_result.scalars().all()}

    # Build seed_book_id map for "Because you read X" attribution
    seed_map = {r["book_id"]: r.get("seed_book_id") for r in recs}

    # Fetch seed book titles
    seed_ids = {sid for sid in seed_map.values() if sid}
    seed_titles = {}
    if seed_ids:
        seed_result = await db.execute(
            select(Book.id, Book.title, Book.epub_title).where(Book.id.in_(seed_ids))
        )
        for row in seed_result.all():
            seed_titles[row[0]] = row[1] or row[2] or ""

    items = []
    for bid in book_ids:
        book = books.get(bid)
        if not book:
            continue
        item = BookWithInteractionOut.model_validate(book)
        interaction = interactions.get(bid)
        if interaction:
            item.reading_status = interaction.reading_status
            item.is_favorite = interaction.is_favorite
            progress = interaction.reading_progress or {}
            item.reading_percentage = progress.get("percentage")
            item.last_read_at = progress.get("last_read_at")
        seed_id = seed_map.get(bid)
        item.seed_book_id = seed_id
        if seed_id:
            item.seed_book_title = seed_titles.get(seed_id)
        items.append(item)

    return items


@router.get("/discover/browse")
async def get_discover_browse(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str = Query(..., pattern="^(genre|subgenre|mood|theme|trope)$"),
    limit_per_tag: int = Query(8, ge=1, le=20),
    max_tags: int = Query(10, ge=1, le=30),
):
    """Browse books by tag category."""
    from app.schemas.tag import TagBrowseSection
    from app.services.recommendations import get_books_by_tag_category
    from app.services.tags import TAG_LABELS

    sections_data = await get_books_by_tag_category(
        db,
        current_user.id,
        is_admin=current_user.role == UserRole.admin,
        category=category,
        limit_per_tag=limit_per_tag,
        max_tags=max_tags,
    )

    sections = []
    for section in sections_data:
        if not section["book_ids"]:
            continue
        result = await db.execute(select(Book).where(Book.id.in_(section["book_ids"])))
        books = list(result.scalars().all())
        sections.append(
            TagBrowseSection(
                tag=section["tag"],
                label=TAG_LABELS.get(section["tag"], section["tag"]),
                category=section["category"],
                book_count=section["book_count"],
                books=[BookOut.model_validate(b) for b in books],
            )
        )

    return sections


@router.get("/all", response_model=PaginatedBooks)
async def list_all_books(
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
    """List all books across accessible libraries."""
    from sqlalchemy import String as SAString
    from sqlalchemy import cast
    from sqlalchemy.sql.functions import coalesce

    # Subquery: accessible book IDs (avoids DISTINCT on the main query)
    accessible_ids = select(LibraryBook.book_id)
    if current_user.role != UserRole.admin:
        accessible_ids = accessible_ids.join(
            Library, Library.id == LibraryBook.library_id
        ).where(
            ~exists(
                select(UserLibraryExclusion.library_id).where(
                    UserLibraryExclusion.user_id == current_user.id,
                    UserLibraryExclusion.library_id == Library.id,
                )
            )
        )

    base_query = select(Book).where(Book.id.in_(accessible_ids))

    # Apply filters
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

    # Apply sorting and pagination
    sort_map = {
        "display_title": coalesce(Book.title, Book.epub_title),
        "added_at": coalesce(Book.calibre_added_at, Book.created_at),
        "series_index": coalesce(Book.series_index, Book.epub_series_index),
    }
    if series and sort == "created_at":
        sort = "series_index"
        order = "asc"
    sort_col = sort_map.get(sort, getattr(Book, sort, Book.created_at))
    if sort == "series_index":
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


@router.get("/{book_id}", response_model=BookOut)
async def get_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _get_book_with_access(book_id, current_user, db)
    # Find libraries this book belongs to
    lb_result = await db.execute(
        select(Library.id, Library.name)
        .join(LibraryBook, LibraryBook.library_id == Library.id)
        .where(LibraryBook.book_id == book_id)
    )
    libraries = lb_result.all()
    out = BookOut.model_validate(book)
    out.library_id = libraries[0].id if libraries else None
    out.library_names = [lib.name for lib in libraries]

    # Check for unresolved reports
    from app.models.book_report import BookReport

    report_result = await db.execute(
        select(BookReport.id)
        .where(BookReport.book_id == book_id, BookReport.resolved.is_(False))
        .limit(1)
    )
    out.has_unresolved_reports = report_result.scalar_one_or_none() is not None
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
    if current_user.role != UserRole.admin and not current_user.can_download:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download permission required",
        )
    book = await _get_book_with_access(book_id, current_user, db)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    # Set filename for browser download
    title = book.title or book.epub_title or "book"
    filename = f"{title}.epub"
    return FileResponse(
        book.file_path,
        media_type="application/epub+zip",
        filename=filename,
    )


@router.get("/{book_id}/content/{path:path}")
async def get_book_content(
    book_id: uuid.UUID,
    path: str,
    current_user: Annotated[User, Depends(get_current_user)],
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

    # Fix malformed XHTML: self-close void elements (e.g. <link ...> → <link .../>)
    if path.endswith((".xhtml", ".html", ".htm")):
        text = data.decode("utf-8", errors="replace")
        text = re.sub(
            r"<(meta|link|br|hr|img|input|source|col|area|base|embed|track|wbr)"
            r"(\s[^>]*?)(?<!/)>",
            r"<\1\2/>",
            text,
        )
        data = text.encode("utf-8")

    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


@router.get("/{book_id}/images")
async def list_epub_images(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all images embedded in the EPUB file."""
    book = await _get_book_with_access(book_id, current_user, db)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    with zipfile.ZipFile(book.file_path, "r") as zf:
        return [
            {"path": name, "name": os.path.basename(name)}
            for name in sorted(zf.namelist())
            if os.path.splitext(name)[1].lower() in image_exts
        ]


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
    fetch_metadata.apply_async(args=[str(book_id)], link=auto_tag_book.si(str(book_id)))
    return {"status": "queued"}


@router.get("/{book_id}/similar")
async def get_similar_books_endpoint(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(10, ge=1, le=50),
):
    """Get books similar to this one, with similarity scores."""
    from app.services.recommendations import get_similar_books

    await _get_book_with_access(book_id, current_user, db)
    similar = await get_similar_books(
        db,
        book_id,
        current_user.id,
        is_admin=current_user.role == UserRole.admin,
        limit=limit,
    )
    if not similar:
        return []

    result = await db.execute(
        select(Book).where(Book.id.in_([s["book_id"] for s in similar]))
    )
    books = {b.id: b for b in result.scalars().all()}

    # Build response with scores, ordered by total_score
    similar_map = {s["book_id"]: s for s in similar}
    ordered = sorted(
        books.values(),
        key=lambda b: similar_map.get(b.id, {}).get("score", 0),
        reverse=True,
    )

    from app.schemas.tag import SimilarBookOut

    return [
        SimilarBookOut(
            **BookOut.model_validate(book, from_attributes=True).model_dump(),
            similarity_score=similar_map.get(book.id, {}).get("score", 0),
            cosine_similarity=similar_map.get(book.id, {}).get("cosine_similarity"),
        )
        for book in ordered
    ]


@router.get("/{book_id}/series-neighbors", response_model=SeriesNeighborsOut)
async def get_series_neighbors(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get next/previous books in the same series, with series progress."""
    book = await _get_book_with_access(book_id, current_user, db)

    series_name = book.display_series
    current_index = book.display_series_index
    if not series_name:
        return SeriesNeighborsOut()

    is_admin = current_user.role == UserRole.admin
    series_col = coalesce(Book.series, Book.epub_series)
    index_col = coalesce(Book.series_index, Book.epub_series_index)

    # Accessible libraries subquery (deny-list: exclude libraries user is excluded from)
    if is_admin:
        accessible_libs = select(Library.id).scalar_subquery()
    else:
        accessible_libs = (
            select(Library.id)
            .where(
                ~exists(
                    select(UserLibraryExclusion.library_id).where(
                        UserLibraryExclusion.user_id == current_user.id,
                        UserLibraryExclusion.library_id == Library.id,
                    )
                )
            )
            .scalar_subquery()
        )

    # Subquery: book IDs accessible to this user
    accessible_book_ids = (
        select(LibraryBook.book_id)
        .where(LibraryBook.library_id.in_(accessible_libs))
        .scalar_subquery()
    )

    # Base: books in same series within accessible libraries (excluding current)
    base = select(Book).where(
        series_col == series_name,
        index_col.isnot(None),
        Book.id != book_id,
        Book.id.in_(accessible_book_ids),
    )

    next_book = None
    prev_book = None

    if current_index is not None:
        # Next: smallest index > current (prefer newest edition if same index)
        result = await db.execute(
            base.where(index_col > current_index)
            .order_by(index_col.asc(), Book.created_at.desc())
            .limit(1)
        )
        next_book = result.scalar_one_or_none()

        # Previous: largest index < current (prefer newest edition if same index)
        result = await db.execute(
            base.where(index_col < current_index)
            .order_by(index_col.desc(), Book.created_at.desc())
            .limit(1)
        )
        prev_book = result.scalar_one_or_none()

    # Series progress: count distinct volumes (not books, since editions share index)
    total_result = await db.execute(
        select(func.count(func.distinct(index_col)))
        .select_from(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(
            series_col == series_name,
            index_col.isnot(None),
            LibraryBook.library_id.in_(accessible_libs),
        )
    )
    total_in_library = total_result.scalar() or 0

    read_result = await db.execute(
        select(func.count(func.distinct(index_col)))
        .select_from(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .join(
            UserBookInteraction,
            (UserBookInteraction.book_id == Book.id)
            & (UserBookInteraction.user_id == current_user.id),
        )
        .where(
            series_col == series_name,
            index_col.isnot(None),
            LibraryBook.library_id.in_(accessible_libs),
            UserBookInteraction.reading_status == "read",
        )
    )
    read_count = read_result.scalar() or 0

    def _brief(b: Book) -> SeriesBookBrief:
        return SeriesBookBrief(
            id=b.id,
            title=b.display_title,
            authors=b.display_authors,
            cover_path=b.cover_path,
            series_index=b.display_series_index,
        )

    return SeriesNeighborsOut(
        series_name=series_name,
        current_index=current_index,
        next=_brief(next_book) if next_book else None,
        previous=_brief(prev_book) if prev_book else None,
        progress=SeriesProgress(
            total_in_library=total_in_library,
            read_count=read_count,
        ),
    )


@router.post("/{book_id}/retag")
async def retag_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Re-run AI tagging for a book (admin only)."""
    await _get_book_with_access(book_id, current_user, db)
    auto_tag_book.delay(str(book_id))
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


@router.put("/{book_id}/external/{source}/url", response_model=ExternalMetadataOut)
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
        MetadataSource.readmoo: re.compile(r"^https://readmoo\.com/book/\d+$"),
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
    current_user: Annotated[User, Depends(get_current_user)],
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

    # Trigger text extraction + summary generation in the background
    if body.section_index is not None:
        from app.tasks.summarize import summarize_chunks

        extract_book_text.delay(str(book_id))
        summarize_chunks.delay(str(book_id), body.section_index)

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


# --- Book Reports ---


@router.post(
    "/{book_id}/reports",
    response_model=BookReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_book_report(
    book_id: uuid.UUID,
    body: BookReportCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.book_report import ISSUE_TYPES, BookReport

    book = await _get_book_with_access(book_id, current_user, db)
    if body.issue_type not in ISSUE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid issue_type. Must be one of: {', '.join(sorted(ISSUE_TYPES))}",
        )
    if body.description and len(body.description) > 2000:
        raise HTTPException(
            status_code=422, detail="Description must be 2000 characters or less"
        )
    report = BookReport(
        book_id=book.id,
        reported_by=current_user.id,
        issue_type=body.issue_type,
        description=body.description,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    out = BookReportOut.model_validate(report)
    out.book_title = book.title or book.epub_title
    out.book_cover = book.cover_path
    return out


@router.get("/{book_id}/reports", response_model=list[BookReportOut])
async def get_book_reports(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.book_report import BookReport

    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(BookReport)
        .where(BookReport.book_id == book_id)
        .order_by(BookReport.created_at.desc())
    )
    reports = result.scalars().all()
    return [BookReportOut.model_validate(r) for r in reports]
