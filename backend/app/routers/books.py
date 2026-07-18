import asyncio
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
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, exists, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import coalesce

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book, ExternalMetadata
from app.models.book_locations import BookLocations
from app.models.library import Library, LibraryBook, UserLibraryExclusion
from app.models.reading import ReadingActivity, UserBookInteraction
from app.models.tag import BookTag
from app.models.user import User, UserRole
from app.plugins.metadata import registry as metadata_registry
from app.plugins.metadata.service import lookup_isbn_all
from app.rate_limit import limiter
from app.schemas.book import (
    BookLibraryUpdate,
    BookLocationsIn,
    BookLocationsOut,
    BookMetadataUpdate,
    BookOut,
    BookSearchResult,
    BookWithInteractionOut,
    ExternalMetadataOut,
    ExternalMetadataUrlUpdate,
    IsbnCoverCandidate,
    IsbnLookupOut,
    IsbnSourceResult,
    PaginatedBookSearchResults,
    PaginatedBooksWithInteraction,
    PhysicalBookCreate,
    SeriesBookBrief,
    SeriesNeighborsOut,
    SeriesProgress,
)
from app.schemas.reading import (
    ReadingActivityOut,
    ReadingGoalUpdate,
    ReadingStatsOut,
)
from app.schemas.series import PaginatedFeed
from app.services.epub_parser import extract_cover, parse_epub_metadata
from app.services.partial_md5 import compute_partial_md5
from app.services.settings import get_all_settings, get_setting
from app.services.storage import (
    cover_url_allowed,
    delete_file,
    download_cover,
    get_book_path,
    get_cover_path,
    save_upload_file,
)
from app.tasks.auto_tag import auto_tag_book
from app.tasks.metadata import fetch_book_metadata, fetch_metadata_source
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


async def _today_in_app_timezone(db: AsyncSession) -> date:
    """Today's date in the configured timezone; a bad setting must never 500
    (it would break every progress save), so fall back to UTC."""
    tz_name = await get_setting(db, "timezone")
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.now(UTC).date()


def book_search_conditions(q: str) -> list:
    """The shared 7-column book search filter (books/all-books/library search).

    The authors arrays are matched through beepub_join_authors() — an
    IMMUTABLE SQL function created in migration 044 — so the trigram
    expression indexes on those columns apply. Keep the two in sync.
    """
    pattern = f"%{q}%"
    return [
        Book.title.ilike(pattern),
        Book.epub_title.ilike(pattern),
        func.beepub_join_authors(Book.authors).ilike(pattern),
        func.beepub_join_authors(Book.epub_authors).ilike(pattern),
        Book.series.ilike(pattern),
        Book.epub_series.ilike(pattern),
        Book.epub_isbn.ilike(pattern),
    ]


def _require_book_file(book: Book) -> None:
    # Physical books (format="physical") have no file behind them.
    if book.file_path is None:
        raise HTTPException(
            status_code=409, detail="This is a physical book — it has no file"
        )


def _require_upload_permission(user: User) -> None:
    if user.role != UserRole.admin and not user.can_upload:
        raise HTTPException(status_code=403, detail="Upload permission required")


async def _validate_upload_library(
    library_id: str | None, user: User, db: AsyncSession
) -> uuid.UUID:
    """Parse and authorize the target library BEFORE any file hits disk."""
    from app.routers.libraries import _get_accessible_library

    # Every book must belong to a library: every listing (all/feed/search/
    # random) reaches books through library membership, so a library-less
    # book would be invisible to everyone — including its uploader.
    if not library_id:
        raise HTTPException(status_code=422, detail="library_id is required")
    try:
        lib_id = uuid.UUID(library_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid library id")
    library = await _get_accessible_library(lib_id, user, db)
    if library.calibre_path:
        raise HTTPException(
            status_code=403, detail="Cannot upload to a Calibre library"
        )
    return lib_id


async def _ingest_epub(
    file: UploadFile, user: User, lib_id: uuid.UUID | None, db: AsyncSession
) -> Book:
    """Save one EPUB to disk and stage its Book row (no commit).

    Cleans up the on-disk files if parsing fails, so a corrupt upload
    doesn't leave orphans behind.
    """
    book_id = uuid.uuid4()
    file_path = get_book_path(book_id, file.filename or "book.epub")
    cover_path = get_cover_path(book_id)

    file_size = await save_upload_file(file, file_path)
    try:
        # EPUB parsing is blocking zip/XML work — keep it off the event loop
        # (a bulk upload would otherwise stall every other request).
        metadata = await asyncio.to_thread(parse_epub_metadata, file_path)
        cover_ok = await asyncio.to_thread(extract_cover, file_path, cover_path)
    except Exception:
        delete_file(file_path)
        delete_file(cover_path)
        raise HTTPException(status_code=400, detail="Invalid EPUB file")

    book = Book(
        id=book_id,
        file_path=file_path,
        file_size=file_size,
        format="epub",
        cover_path=cover_path if cover_ok else None,
        partial_md5=await asyncio.to_thread(compute_partial_md5, file_path),
        added_by=user.id,
        **metadata,
    )
    db.add(book)
    await db.flush()
    if lib_id:
        db.add(LibraryBook(library_id=lib_id, book_id=book_id, added_by=user.id))
    return book


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def upload_book(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    library_id: str = Form(...),
):
    _require_upload_permission(current_user)
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Only EPUB files are supported")

    lib_id = await _validate_upload_library(library_id, current_user, db)
    book = await _ingest_epub(file, current_user, lib_id, db)

    await db.commit()
    await db.refresh(book)

    extract_book_text.delay(str(book.id))
    fetch_book_metadata.delay(str(book.id))
    return book


@router.post("/bulk", response_model=list[BookOut], status_code=status.HTTP_201_CREATED)
async def upload_books_bulk(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    library_id: str = Form(...),
):
    _require_upload_permission(current_user)
    lib_id = await _validate_upload_library(library_id, current_user, db)

    books = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".epub"):
            continue
        books.append(await _ingest_epub(file, current_user, lib_id, db))

    await db.commit()
    for book in books:
        await db.refresh(book)
        extract_book_text.delay(str(book.id))
        fetch_book_metadata.delay(str(book.id))
    return books


@router.post("/physical", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_physical_book(
    body: PhysicalBookCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Track a paper copy: a Book row with no file behind it."""
    _require_upload_permission(current_user)
    lib_id = await _validate_upload_library(str(body.library_id), current_user, db)

    book_id = uuid.uuid4()
    cover_path = None
    if body.cover_url:
        if not cover_url_allowed(body.cover_url):
            raise HTTPException(status_code=422, detail="cover_url host is not allowed")
        dest = get_cover_path(book_id)
        if await download_cover(body.cover_url, dest):
            cover_path = dest

    book = Book(
        id=book_id,
        file_path=None,
        file_size=None,
        format="physical",
        cover_path=cover_path,
        # "" is the established no-digest marker — non-NULL so the digest
        # backfill scan never picks the book up.
        partial_md5="",
        # False (not NULL) keeps the text-extraction scan from queueing it.
        is_image_book=False,
        added_by=current_user.id,
        # Physical books have no EPUB source metadata; everything lives in
        # the manual-override columns (which win in display anyway).
        title=body.title,
        authors=body.authors or None,
        publisher=body.publisher,
        description=body.description,
        published_date=body.published_date,
        series=body.series,
        series_index=body.series_index,
        epub_isbn=body.isbn,
        epub_language=body.language,
    )
    db.add(book)
    await db.flush()
    db.add(LibraryBook(library_id=lib_id, book_id=book_id, added_by=current_user.id))
    await db.commit()
    await db.refresh(book)

    # External ratings/reviews and auto-tagging work from metadata alone;
    # text extraction is meaningless without a file and is not queued.
    fetch_book_metadata.delay(str(book.id))
    return book


@router.put("/{book_id}/library")
async def move_book_to_library(
    book_id: uuid.UUID,
    body: BookLibraryUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set the library a book belongs to (a book lives in exactly one)."""
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    if not book_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Book not found")

    lib_result = await db.execute(select(Library).where(Library.id == body.library_id))
    target = lib_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Library not found")
    if target.calibre_path:
        raise HTTPException(
            status_code=403, detail="Cannot move books into a Calibre library"
        )

    membership_result = await db.execute(
        select(LibraryBook).where(LibraryBook.book_id == book_id)
    )
    membership = membership_result.scalar_one_or_none()
    if membership is not None and membership.library_id == body.library_id:
        return {"status": "unchanged"}

    from app.services.work_library import book_is_in_work

    if await book_is_in_work(book_id, db):
        # A Work's editions must live in one library — move them together
        # or not at all.
        raise HTTPException(
            status_code=409,
            detail=(
                "Book is part of a Work. Dissolve the Work first, "
                "or move all its editions together."
            ),
        )

    if membership is None:
        # Legacy orphan (pre-invariant data) — adopt it into the target.
        db.add(
            LibraryBook(
                library_id=body.library_id,
                book_id=book_id,
                added_by=current_user.id,
            )
        )
    else:
        source = await db.get(Library, membership.library_id)
        if source is not None and source.calibre_path:
            raise HTTPException(
                status_code=403,
                detail="Cannot move books out of a Calibre library",
            )
        membership.library_id = body.library_id
        membership.added_by = current_user.id
    await db.commit()
    return {"status": "moved"}


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

    # One row per date: devices each own their rows, the heatmap shows the sum.
    result = await db.execute(
        select(
            ReadingActivity.date,
            func.sum(ReadingActivity.seconds).label("seconds"),
        )
        .where(
            ReadingActivity.user_id == current_user.id,
            extract("year", ReadingActivity.date) == year,
        )
        .group_by(ReadingActivity.date)
        .order_by(ReadingActivity.date)
    )
    return [{"date": r.date, "seconds": r.seconds} for r in result.all()]


@router.get("/reading-stats", response_model=ReadingStatsOut)
async def get_reading_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get reading streak and goal progress for the current user."""
    today = await _today_in_app_timezone(db)

    # Fetch all reading days ordered by date desc. Summed across devices —
    # the streak helpers require DISTINCT dates (a duplicate date would
    # reset the longest-streak walk).
    result = await db.execute(
        select(
            ReadingActivity.date,
            func.sum(ReadingActivity.seconds).label("seconds"),
        )
        .where(ReadingActivity.user_id == current_user.id)
        .group_by(ReadingActivity.date)
        .having(func.sum(ReadingActivity.seconds) > 0)
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
    from app.models.work import Work
    from app.routers.libraries import accessible_libraries_condition

    if sort not in {"last_read_at", "updated_at", "display_title"}:
        sort = "last_read_at"
    if order not in {"asc", "desc"}:
        order = "desc"

    # CTE 1 — accessible books: book IDs in libraries the user can see
    accessible_q = (
        select(LibraryBook.book_id.label("book_id"))
        .join(Library, Library.id == LibraryBook.library_id)
        .distinct()
    )
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_q = accessible_q.where(cond)
    accessible = accessible_q.cte("accessible")

    # CTE 2 — user's interactions on accessible books
    ubi = (
        select(
            UserBookInteraction.book_id.label("book_id"),
            UserBookInteraction.reading_status.label("reading_status"),
            UserBookInteraction.is_favorite.label("is_favorite"),
            UserBookInteraction.reading_progress.label("reading_progress"),
            UserBookInteraction.updated_at.label("updated_at"),
        )
        .where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id.in_(select(accessible.c.book_id)),
        )
        .cte("ubi")
    )

    # CTE 3 — map each interacted book → its display book (Work primary or self).
    # The Work single-library invariant (services/work_library.py + the
    # uq_library_books_book_id constraint) guarantees the primary edition is
    # accessible whenever any sibling is, so no extra accessibility filter
    # is needed here — `ubi` is already accessibility-scoped.
    book_dm = aliased(Book)
    display_book_id_expr = coalesce(Work.primary_book_id, book_dm.id)
    display_map = (
        select(
            display_book_id_expr.label("display_book_id"),
            book_dm.work_id.label("work_id"),
        )
        .select_from(ubi)
        .join(book_dm, book_dm.id == ubi.c.book_id)
        .outerjoin(
            Work,
            and_(Work.id == book_dm.work_id, Work.primary_book_id.isnot(None)),
        )
        .distinct()
        .cte("display_map")
    )

    # CTE 4 — expand each display book to all Work editions (or just self if standalone).
    sib = aliased(Book)
    siblings = (
        select(
            display_map.c.display_book_id.label("display_book_id"),
            sib.id.label("sibling_id"),
        )
        .select_from(display_map)
        .join(
            sib,
            or_(
                and_(
                    display_map.c.work_id.isnot(None),
                    sib.work_id == display_map.c.work_id,
                ),
                and_(
                    display_map.c.work_id.is_(None),
                    sib.id == display_map.c.display_book_id,
                ),
            ),
        )
        .cte("siblings")
    )

    # CTE 5 — siblings ⨝ ubi: every interacted edition for each Work the user touched.
    sib_ubi = (
        select(
            siblings.c.display_book_id.label("display_book_id"),
            ubi.c.reading_status.label("reading_status"),
            ubi.c.is_favorite.label("is_favorite"),
            ubi.c.reading_progress.label("reading_progress"),
            ubi.c.updated_at.label("updated_at"),
        )
        .select_from(siblings)
        .join(ubi, ubi.c.book_id == siblings.c.sibling_id)
        .cte("sib_ubi")
    )

    from app.services.work_propagation import best_reading_status_expr

    # CTE 6 — work-level aggregates. best_reading_status_expr keeps the same
    # priority logic as the work-propagation lookup so the two can't drift apart;
    # NULL reading_status (e.g. favorite-only interactions) stays NULL rather than
    # being bucketed into want_to_read.
    work_last_read_at = func.max(sib_ubi.c.reading_progress["last_read_at"].astext)
    agg = (
        select(
            sib_ubi.c.display_book_id.label("display_book_id"),
            best_reading_status_expr(sib_ubi.c.reading_status).label("best_status"),
            func.bool_or(sib_ubi.c.is_favorite).label("any_favorite"),
            func.max(sib_ubi.c.updated_at).label("work_last_updated_at"),
            work_last_read_at.label("work_last_read_at"),
        )
        .group_by(sib_ubi.c.display_book_id)
        .cte("agg")
    )

    # Final query — join the display book's own interaction (per-edition progress is
    # NOT aggregated across siblings: percentage and CFI are tied to a specific EPUB).
    own_ubi = aliased(UserBookInteraction)
    base = (
        select(
            agg.c.display_book_id,
            agg.c.best_status,
            agg.c.any_favorite,
            agg.c.work_last_read_at,
            agg.c.work_last_updated_at,
            own_ubi.reading_progress.label("own_progress"),
        )
        .select_from(agg)
        .join(Book, Book.id == agg.c.display_book_id)
        .outerjoin(
            own_ubi,
            and_(
                own_ubi.book_id == agg.c.display_book_id,
                own_ubi.user_id == current_user.id,
            ),
        )
    )
    if reading_status is not None:
        base = base.where(agg.c.best_status == reading_status)
    if favorite is not None:
        base = base.where(agg.c.any_favorite == favorite)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0
    if total == 0:
        return PaginatedBooksWithInteraction(items=[], total=0)

    if sort == "last_read_at":
        sort_col = agg.c.work_last_read_at
    elif sort == "updated_at":
        sort_col = agg.c.work_last_updated_at
    else:
        sort_col = coalesce(Book.title, Book.epub_title)

    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()
    base = base.order_by(sort_expr.nullslast(), agg.c.display_book_id)
    base = base.limit(limit).offset(offset)

    rows = (await db.execute(base)).all()

    book_ids_list = [row.display_book_id for row in rows]
    books_result = await db.execute(select(Book).where(Book.id.in_(book_ids_list)))
    books_map = {b.id: b for b in books_result.scalars().all()}

    from app.services.work_propagation import get_edition_count_map

    edition_counts = await get_edition_count_map(db, book_ids_list)
    items = []
    for row in rows:
        book = books_map.get(row.display_book_id)
        if not book:
            continue
        item = BookWithInteractionOut.model_validate(book)
        item.reading_status = row.best_status
        item.is_favorite = row.any_favorite
        own_progress = row.own_progress or {}
        item.reading_percentage = own_progress.get("percentage")
        item.last_read_at = own_progress.get("last_read_at")
        item.edition_count = edition_counts.get(row.display_book_id)
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
    # An empty library is not an error — the frontend renders its own
    # "nothing to pull" state for an empty list.
    return result.scalars().all()


@router.get("/search", response_model=PaginatedBookSearchResults)
async def search_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query("", min_length=1),
    limit: int = Query(20, ge=1, le=100),
):
    from sqlalchemy import case

    from app.routers.libraries import accessible_libraries_condition

    # Subquery: accessible library IDs
    accessible_libs = select(Library.id)
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_libs = accessible_libs.where(cond)
    accessible_lib_ids = accessible_libs.subquery()

    # Main query: search books in accessible libraries. A book can live in
    # several libraries, so collapse to one row per book (min library name).
    base_query = (
        select(Book, func.min(Library.name).label("library_name"))
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .join(Library, Library.id == LibraryBook.library_id)
        .where(
            LibraryBook.library_id.in_(select(accessible_lib_ids.c.id)),
            or_(*book_search_conditions(q)),
        )
        .group_by(Book.id)
    )

    # Count (one row per distinct book)
    count_sub = base_query.with_only_columns(Book.id).subquery()
    total = (
        await db.execute(select(func.count()).select_from(count_sub))
    ).scalar() or 0

    # Rank by relevance so a short query like "小王子" surfaces the closest
    # titles first instead of an arbitrary UUID-ordered slice: exact title
    # match, then title prefix, then any substring; ties broken by shorter
    # (and then alphabetical) title.
    title_col = func.coalesce(Book.title, Book.epub_title)
    relevance = case(
        (func.lower(title_col) == q.lower(), 0),
        (title_col.ilike(f"{q}%"), 1),
        else_=2,
    )
    ranked_query = base_query.order_by(
        relevance, func.length(title_col), title_col, Book.id
    )

    result = await db.execute(ranked_query.limit(limit))
    rows = result.all()

    # Enrich with edition_count
    from app.services.work_propagation import get_edition_count_map

    book_ids_list = [row[0].id for row in rows]
    edition_counts = await get_edition_count_map(db, book_ids_list)
    items = []
    for book, library_name in rows:
        item = BookSearchResult.model_validate(book)
        item.library_name = library_name
        item.edition_count = edition_counts.get(book.id)
        items.append(item)

    return PaginatedBookSearchResults(items=items, total=total)


@router.get("/discover/recommendations", response_model=list[BookWithInteractionOut])
async def get_discover_recommendations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(30, ge=1, le=50),
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

    # Work-level propagation
    from app.services.work_propagation import (
        get_edition_count_map,
        get_work_propagated_interactions,
    )

    propagated = await get_work_propagated_interactions(db, book_ids, current_user.id)
    edition_counts = await get_edition_count_map(db, book_ids)
    items = []
    for bid in book_ids:
        book = books.get(bid)
        if not book:
            continue
        item = BookWithInteractionOut.model_validate(book)
        interaction = interactions.get(bid)
        prop = propagated.get(bid)
        if interaction:
            item.reading_status = interaction.reading_status
            item.is_favorite = interaction.is_favorite
            progress = interaction.reading_progress or {}
            item.reading_percentage = progress.get("percentage")
            item.last_read_at = progress.get("last_read_at")
        elif prop:
            item.reading_status = prop["reading_status"]
            item.is_favorite = prop["is_favorite"]
        item.edition_count = edition_counts.get(bid)
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

    all_ids = {bid for s in sections_data for bid in s["book_ids"]}
    if all_ids:
        result = await db.execute(select(Book).where(Book.id.in_(all_ids)))
        book_map = {b.id: b for b in result.scalars().all()}
    else:
        book_map = {}

    from app.services.work_propagation import get_work_propagated_interactions

    propagated = await get_work_propagated_interactions(
        db, list(all_ids), current_user.id
    )

    def _to_item(b: Book) -> BookWithInteractionOut:
        item = BookWithInteractionOut.model_validate(b)
        prop = propagated.get(b.id)
        if prop:
            item.reading_status = prop["reading_status"]
            item.is_favorite = prop["is_favorite"]
        return item

    sections = []
    for section in sections_data:
        if not section["book_ids"]:
            continue
        books = [book_map[bid] for bid in section["book_ids"] if bid in book_map]
        sections.append(
            TagBrowseSection(
                tag=section["tag"],
                label=TAG_LABELS.get(section["tag"], section["tag"]),
                category=section["category"],
                book_count=section["book_count"],
                books=[_to_item(b) for b in books],
            )
        )

    return sections


@router.get("/all", response_model=PaginatedBooksWithInteraction)
async def list_all_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    series: str | None = Query(None),
    format: str | None = Query(None),
    library: uuid.UUID | None = Query(None),
    has_rating: bool = Query(False),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all books across accessible libraries.

    ``library`` scopes the result to one library — used with ``series`` so the
    series-detail page only shows that library's volumes (series identity is
    ``(library_id, series_key)``).
    """
    from sqlalchemy.sql.functions import coalesce

    from app.routers.libraries import accessible_book_ids_select

    # Accessible book IDs (avoids DISTINCT on the main query)
    accessible_ids = accessible_book_ids_select(current_user)

    base_query = select(Book).where(Book.id.in_(accessible_ids))

    # Apply filters
    if search:
        base_query = base_query.where(or_(*book_search_conditions(search)))
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
    if format:
        base_query = base_query.where(Book.format == format)
    if library:
        base_query = base_query.where(
            Book.id.in_(
                select(LibraryBook.book_id).where(LibraryBook.library_id == library)
            )
        )
    if has_rating:
        base_query = base_query.where(
            Book.id.in_(
                select(UserBookInteraction.book_id).where(
                    UserBookInteraction.user_id == current_user.id,
                    UserBookInteraction.rating.is_not(None),
                )
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
        "popularity_score": Book.popularity_score,
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
    books = result.scalars().all()

    # Enrich with edition_count + work-propagated reading status. The page is
    # bounded by `limit` (<=200), so propagation runs only over the current page.
    from app.services.work_propagation import (
        get_edition_count_map,
        get_work_propagated_interactions,
    )

    book_ids_list = [b.id for b in books]
    edition_counts = await get_edition_count_map(db, book_ids_list)
    propagated = await get_work_propagated_interactions(
        db, book_ids_list, current_user.id
    )
    # Direct (non-propagated) user interaction for this page of books —
    # rating, plus progress for the grid's "n%" status line (progress stays
    # per-edition, so it deliberately does not propagate across works).
    own_result = await db.execute(
        select(
            UserBookInteraction.book_id,
            UserBookInteraction.rating,
            UserBookInteraction.reading_progress,
        ).where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.book_id.in_(book_ids_list),
        )
    )
    own_map = {row[0]: row for row in own_result.all()}
    items = []
    for b in books:
        item = BookWithInteractionOut.model_validate(b)
        item.edition_count = edition_counts.get(b.id)
        prop = propagated.get(b.id)
        if prop:
            item.reading_status = prop["reading_status"]
            item.is_favorite = prop["is_favorite"]
        own = own_map.get(b.id)
        if own:
            item.user_rating = own.rating
            own_progress = own.reading_progress or {}
            item.reading_percentage = own_progress.get("percentage")
            item.last_read_at = own_progress.get("last_read_at")
        items.append(item)

    return PaginatedBooksWithInteraction(items=items, total=total)


@router.get("/feed", response_model=PaginatedFeed)
async def list_all_books_feed(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    sort: str = Query("added_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Collapsed view across all accessible libraries: series grouped, lone
    books individual. The "All books" tab in the merged library page."""
    from app.services.series import list_library_feed

    items, total = await list_library_feed(
        db,
        current_user,
        library_id=None,
        search=search,
        author=author,
        tag=tag,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return PaginatedFeed(items=items, total=total)


@router.get("/isbn-lookup", response_model=IsbnLookupOut)
@limiter.limit("10/minute")
async def isbn_lookup(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    isbn: str = Query(min_length=5, max_length=20),
):
    """Fan the ISBN out to every capable enabled plugin and return the
    per-source results with provenance. Always 200 — empty lists mean
    nothing was found anywhere."""
    _require_upload_permission(current_user)
    app_settings = await get_all_settings(db)

    results: list[IsbnSourceResult] = []
    covers: list[IsbnCoverCandidate] = []
    seen_cover_urls: set[str] = set()
    for name, record in await lookup_isbn_all(isbn, app_settings):
        plugin_cls = metadata_registry.get_plugin_class(name)
        label = plugin_cls.label if plugin_cls else name
        # Records without a title (cover-only degradations) still feed
        # the cover candidates but don't become a pickable source.
        if record.title:
            results.append(
                IsbnSourceResult(
                    source=name,
                    label=label,
                    title=record.title,
                    authors=record.authors,
                    publisher=record.publisher,
                    description=record.description,
                    published_date=record.published_date,
                    language=record.language,
                    cover_url=record.cover_url,
                )
            )
        if record.cover_url and record.cover_url not in seen_cover_urls:
            seen_cover_urls.add(record.cover_url)
            covers.append(
                IsbnCoverCandidate(source=name, label=label, url=record.cover_url)
            )
    return IsbnLookupOut(results=results, covers=covers)


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


@router.get("/{book_id}/locations", response_model=BookLocationsOut)
async def get_book_locations(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Shared cache of epub.js-generated locations.

    Locations are deterministic per book file, so the first client to
    generate them serves every user and device. 204 = nobody has yet;
    the client generates and PUTs them back.
    """
    await _get_book_with_access(book_id, current_user, db)
    row = (
        await db.execute(select(BookLocations).where(BookLocations.book_id == book_id))
    ).scalar_one_or_none()
    if row is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return row


@router.put("/{book_id}/locations")
async def put_book_locations(
    book_id: uuid.UUID,
    body: BookLocationsIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _get_book_with_access(book_id, current_user, db)
    _require_book_file(book)
    row = (
        await db.execute(select(BookLocations).where(BookLocations.book_id == book_id))
    ).scalar_one_or_none()
    if row is None:
        row = BookLocations(book_id=book_id)
        db.add(row)
    row.fingerprint = body.fingerprint
    row.locations = body.locations
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return {"status": "stored"}


@router.get("/{book_id}/editions")
async def get_book_editions(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get other editions of the same Work plus the Work's primary_book_id.

    Returns {primary_book_id: null, editions: []} if the book has no Work.
    """
    book = await _get_book_with_access(book_id, current_user, db)
    if not book.work_id:
        return {"primary_book_id": None, "editions": []}

    from app.models.work import Work

    work_result = await db.execute(select(Work).where(Work.id == book.work_id))
    work = work_result.scalar_one_or_none()

    result = await db.execute(
        select(Book)
        .where(Book.work_id == book.work_id, Book.id != book_id)
        .order_by(Book.created_at.desc())
    )
    siblings = result.scalars().all()
    return {
        "primary_book_id": work.primary_book_id if work else None,
        "editions": [
            {
                "id": b.id,
                "display_title": b.display_title,
                "display_authors": b.display_authors,
                "cover_path": b.cover_path,
                "epub_isbn": b.epub_isbn,
                "metadata_count": b.metadata_count,
                "created_at": b.created_at,
            }
            for b in siblings
        ],
    }


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
    series_will_change = (
        "series" in body.model_fields_set and data["series"] != book.series
    ) or (
        "epub_series" in body.model_fields_set
        and data["epub_series"] != book.epub_series
    )
    old_series_sibling_id: uuid.UUID | None = None
    if series_will_change:
        old_key = (book.series or book.epub_series or "").strip().lower() or None
        if old_key:
            sibling = await db.execute(
                select(Book.id)
                .where(
                    Book.id != book.id,
                    func.lower(func.btrim(func.coalesce(Book.series, Book.epub_series)))
                    == old_key,
                )
                .limit(1)
            )
            old_series_sibling_id = sibling.scalar_one_or_none()

    for field in body.model_fields_set:
        setattr(book, field, data[field])
    await db.flush()

    if series_will_change:
        from app.services.popularity import recompute_popularity

        affected = [book.id] + (
            [old_series_sibling_id] if old_series_sibling_id else []
        )
        await recompute_popularity(db, affected)

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
    # Only delete the EPUB file for non-Calibre books (Calibre files are on
    # a read-only mount). Files are removed AFTER the commit — if the commit
    # fails, a row pointing at a deleted file would be unrecoverable.
    paths = []
    if book.calibre_id is None and book.file_path:
        paths.append(book.file_path)
    if book.cover_path:
        paths.append(book.cover_path)
    work_id = book.work_id
    await db.delete(book)
    if work_id:
        from app.services.work_library import cleanup_orphan_works

        await cleanup_orphan_works(db, [work_id])
    await db.commit()
    for path in paths:
        delete_file(path)


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
    _require_book_file(book)
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
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Serve individual files from within the EPUB zip (for epubjs reader)."""
    book = await _get_book_with_access(book_id, current_user, db)
    _require_book_file(book)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # ETag based on EPUB mtime + path. When Calibre rewrites the EPUB
    # (cover/xhtml edits), mtime advances and the ETag changes, so the
    # browser's cached copy is invalidated naturally.
    epub_mtime = int(os.path.getmtime(book.file_path))
    etag = f'"{epub_mtime:x}-{abs(hash(path)):x}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=86400, must-revalidate",
    }

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    try:
        # Zip decompression + regex rewrite are blocking CPU/disk work and
        # this endpoint fires on every chapter turn — keep it off the event
        # loop so concurrent readers don't serialize behind each other.
        data = await asyncio.to_thread(_read_epub_entry, book.file_path, path)
    except KeyError:
        raise HTTPException(status_code=404, detail="Path not found in EPUB")
    content_type, _ = mimetypes.guess_type(path)
    if content_type is None:
        content_type = "application/octet-stream"

    return Response(
        content=data,
        media_type=content_type,
        headers=headers,
    )


def _read_epub_entry(file_path: str, path: str) -> bytes:
    with zipfile.ZipFile(file_path, "r") as zf:
        data = zf.read(path)

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
    return data


@router.get("/{book_id}/images")
async def list_epub_images(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all images embedded in the EPUB file."""
    book = await _get_book_with_access(book_id, current_user, db)
    _require_book_file(book)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    def scan() -> list[dict]:
        with zipfile.ZipFile(book.file_path, "r") as zf:
            return [
                {"path": name, "name": os.path.basename(name)}
                for name in sorted(zf.namelist())
                if os.path.splitext(name)[1].lower() in image_exts
            ]

    return await asyncio.to_thread(scan)


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
    fetch_book_metadata.delay(str(book_id))
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

    # Dedup by Work: keep only the highest-scoring book per Work
    seen_work_ids: set[uuid.UUID] = set()
    deduped = []
    for book in ordered:
        if book.work_id:
            if book.work_id in seen_work_ids:
                continue
            seen_work_ids.add(book.work_id)
        deduped.append(book)

    from app.schemas.tag import SimilarBookOut

    return [
        SimilarBookOut(
            **BookOut.model_validate(book, from_attributes=True).model_dump(),
            similarity_score=similar_map.get(book.id, {}).get("score", 0),
            cosine_similarity=similar_map.get(book.id, {}).get("cosine_similarity"),
        )
        for book in deduped
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

    # Series identity is scoped per library, so neighbors stay within the
    # current book's own library set (e.g. a light novel and its manga
    # adaptation share a name but are different series).
    scoped_libs = (
        select(LibraryBook.library_id)
        .where(
            LibraryBook.book_id == book_id,
            LibraryBook.library_id.in_(accessible_libs),
        )
        .scalar_subquery()
    )

    # Subquery: book IDs in the same library set as the current book
    accessible_book_ids = (
        select(LibraryBook.book_id)
        .where(LibraryBook.library_id.in_(scoped_libs))
        .scalar_subquery()
    )

    # Base: books in same series within the current book's libraries (excluding current)
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
    # Work-aware: a volume is "read" if ANY edition in its Work is read by this user
    from sqlalchemy import case

    # Subquery: book IDs that this user has read (direct or via work propagation)
    user_read_books = (
        select(UserBookInteraction.book_id)
        .where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.reading_status == "read",
        )
        .scalar_subquery()
    )

    # A book counts as "read" if it's directly read OR any work-sibling is read
    is_read = or_(
        Book.id.in_(user_read_books),
        exists(
            select(literal_column("1"))
            .select_from(Book.__table__.alias("sibling"))
            .where(
                literal_column("sibling.work_id").isnot(None),
                literal_column("sibling.work_id") == Book.work_id,
                literal_column("sibling.id").in_(user_read_books),
            )
        ),
    )

    progress_result = await db.execute(
        select(
            func.count(func.distinct(index_col)),
            func.max(index_col),
            func.count(
                func.distinct(
                    case(
                        (is_read, index_col),
                    )
                )
            ),
        )
        .select_from(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(
            series_col == series_name,
            index_col.isnot(None),
            LibraryBook.library_id.in_(scoped_libs),
        )
    )
    total_in_library, max_series_index, read_count = progress_result.one()
    total_in_library = total_in_library or 0
    read_count = read_count or 0

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
            max_series_index=max_series_index,
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
    # Validate source against the plugin registry
    plugin_cls = metadata_registry.get_plugin_class(source)
    if plugin_cls is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid source. Must be one of: "
            f"{', '.join(c.name for c in metadata_registry.all_plugins())}",
        )
    validated_source = plugin_cls.name

    enabled_value = await get_setting(
        db, metadata_registry.enabled_key(validated_source)
    )
    if enabled_value == "false":
        raise HTTPException(status_code=409, detail=f"{validated_source} is disabled")

    # Validate source URL format from the plugin's linking declaration
    if body.source_url is not None:
        if not plugin_cls.url_prefix:
            raise HTTPException(
                status_code=400,
                detail=f"{source} does not support manual linking",
            )
        pattern = re.compile(
            "^" + re.escape(plugin_cls.url_prefix) + plugin_cls.id_pattern.lstrip("^")
        )
        if not pattern.match(body.source_url):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid URL format for {source}",
            )

    # Check book exists
    result = await db.execute(select(Book).where(Book.id == book_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Book not found")

    if body.source_url is None:
        # Mark as "not found" — clear data but keep the row as empty marker
        result = await db.execute(
            select(ExternalMetadata).where(
                ExternalMetadata.book_id == book_id,
                ExternalMetadata.source == validated_source,
            )
        )
        meta = result.scalar_one_or_none()
        if meta:
            meta.source_url = None
            meta.rating = None
            meta.rating_count = None
            meta.readers_count = None
            meta.reviews = None
            meta.record = None
        else:
            meta = ExternalMetadata(
                book_id=book_id,
                source=validated_source,
            )
            db.add(meta)
        await db.commit()
        await db.refresh(meta)
        # Re-run tag mapping since we removed a source's data
        from app.services.tag_mapping import generate_tags_from_metadata

        await generate_tags_from_metadata(db, book_id)
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
        # Fetch data from the pinned URL and re-map tags
        fetch_metadata_source.delay(str(book_id), source)
        return meta


@router.delete("/{book_id}/external/{source}", status_code=204)
async def delete_external_metadata(
    book_id: uuid.UUID,
    source: str,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Unlink a source completely — removes the row so it can be re-searched."""
    if metadata_registry.get_plugin_class(source) is None:
        raise HTTPException(status_code=400, detail="Invalid source")
    validated_source = source

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

    # Re-run tag mapping
    from app.services.tag_mapping import generate_tags_from_metadata

    await generate_tags_from_metadata(db, book_id)
    await db.commit()
