import asyncio
import logging
import mimetypes
import os
import re
import shutil
import uuid
import zipfile
import zlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, NamedTuple
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
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import and_, exists, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import coalesce

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book, ExternalMetadata
from app.models.book_text import BookTextChunk
from app.models.library import Library, LibraryBook, UserLibraryExclusion
from app.models.reading import Highlight, ReadingActivity, UserBookInteraction
from app.models.tag import BookTag
from app.models.user import User, UserRole
from app.plugins.metadata import BookQuery, Clue
from app.plugins.metadata import registry as metadata_registry
from app.plugins.metadata.service import lookup_all, resolve_one, search_all
from app.rate_limit import limiter
from app.schemas.book import (
    BookCoverUpdate,
    BookIdsRequest,
    BookLibraryUpdate,
    BookMetadataBulkUpdate,
    BookMetadataUpdate,
    BookOut,
    BookWithInteractionOut,
    ExternalMetadataOut,
    ExternalMetadataUrlUpdate,
    IsbnCoverCandidate,
    IsbnLookupOut,
    IsbnSourceResult,
    MetadataSearchCandidate,
    MetadataSearchOut,
    PaginatedBooksWithInteraction,
    PhysicalBookCreate,
    SeriesBookBrief,
    SeriesNeighborsOut,
    SeriesProgress,
    ZhConversionPreview,
    ZhConversionRequest,
    ZhConversionSegment,
)
from app.schemas.reading import (
    ReadingActivityOut,
    ReadingGoalUpdate,
    ReadingStatsOut,
)
from app.schemas.series import PaginatedGrouped
from app.services.access import (
    accessible_book_ids_select,
    accessible_libraries_condition,
    get_accessible_book,
    get_accessible_library,
)
from app.services.book_cards import book_cards
from app.services.book_files import book_files, invalidate_derived_text
from app.services.book_search import relevance_ranked_ids, tiered_book_search
from app.services.epub_pages import read_page_manifest
from app.services.epub_parser import parse_epub_metadata
from app.services.ingest import (
    UNSUPPORTED_UPLOAD,
    commit_ingested,
    discard_ingested,
    ingest_upload,
    require_upload_permission,
    upload_suffix,
    validate_upload_library,
)
from app.services.metadata_fetch import cached_resolve
from app.services.partial_md5 import compute_partial_md5
from app.services.settings import get_all_settings, get_setting
from app.services.storage import (
    MAX_COVER_DOWNLOAD_SIZE,
    cover_thumbnail_path,
    cover_url_allowed,
    delete_file,
    download_cover,
    get_cover_path,
    get_kept_epub_path,
    place_cover,
    save_cover_bytes,
)
from app.services.zh_epub import (
    Quote,
    convert_epub,
    convert_highlight,
    preview,
    section_of,
)
from app.tasks.auto_tag import auto_tag_book
from app.tasks.metadata import fetch_book_metadata, fetch_metadata_source
from app.tasks.text_extract import extract_book_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


async def _today_in_app_timezone(db: AsyncSession) -> date:
    """Today's date in the configured timezone; a bad setting must never 500
    (it would break every progress save), so fall back to UTC."""
    tz_name = await get_setting(db, "timezone")
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.now(UTC).date()


def _require_book_file(book: Book) -> None:
    # Physical books (format="physical") have no file behind them.
    if book.file_path is None:
        raise HTTPException(
            status_code=409, detail="This is a physical book — it has no file"
        )


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def upload_book(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    library_id: str = Form(...),
):
    require_upload_permission(current_user)
    if upload_suffix(file) is None:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_UPLOAD)

    lib_id = await validate_upload_library(library_id, current_user, db)
    book = await ingest_upload(file, current_user, lib_id, db)
    await commit_ingested(db, [book])
    return book


@router.post("/bulk", response_model=list[BookOut], status_code=status.HTTP_201_CREATED)
async def upload_books_bulk(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    library_id: str = Form(...),
):
    require_upload_permission(current_user)
    lib_id = await validate_upload_library(library_id, current_user, db)

    # All or none: one file that cannot be read refuses the request, and
    # the ones staged before it go with it.
    books: list[Book] = []
    try:
        for file in files:
            if upload_suffix(file) is None:
                continue
            books.append(await ingest_upload(file, current_user, lib_id, db))
    except Exception:
        discard_ingested(books)
        raise
    await commit_ingested(db, books)
    return books


@router.post("/physical", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_physical_book(
    body: PhysicalBookCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Track a paper copy: a Book row with no file behind it."""
    require_upload_permission(current_user)
    lib_id = await validate_upload_library(str(body.library_id), current_user, db)

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

    # (In the order of the rows: a book can have gone since they were read.)
    items = await book_cards(
        db,
        current_user.id,
        [books_map[bid] for bid in book_ids_list if bid in books_map],
    )

    return PaginatedBooksWithInteraction(items=items, total=total)


@router.get("/random", response_model=list[BookOut])
async def get_random_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    count: int = Query(8, ge=1, le=20),
):

    accessible_books = select(LibraryBook.book_id).join(
        Library, Library.id == LibraryBook.library_id
    )
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_books = accessible_books.where(cond)
    accessible_book_ids = accessible_books.subquery()

    # Drawn over ids, the books fetched afterwards: shuffling whole rows
    # sorts the entire table's worth of them.
    drawn = list(
        await db.scalars(
            select(Book.id)
            .where(
                Book.id.in_(select(accessible_book_ids.c.book_id)),
                Book.cover_path.isnot(None),
            )
            .order_by(func.random())
            .limit(count)
        )
    )
    by_id = {
        book.id: book
        for book in await db.scalars(select(Book).where(Book.id.in_(drawn)))
    }
    # An empty library is not an error — the frontend renders its own
    # "nothing to pull" state for an empty list.
    return [by_id[book_id] for book_id in drawn if book_id in by_id]


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

    items = await book_cards(
        db, current_user.id, [books[bid] for bid in book_ids if bid in books]
    )
    for item in items:
        seed_id = seed_map.get(item.id)
        item.seed_book_id = seed_id
        if seed_id:
            item.seed_book_title = seed_titles.get(seed_id)
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
    from app.services.tags import TAG_LABELS, TAG_LABELS_HANS

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

    cards = {
        card.id: card
        for card in await book_cards(db, current_user.id, list(book_map.values()))
    }

    sections = []
    for section in sections_data:
        if not section["book_ids"]:
            continue
        books = [cards[bid] for bid in section["book_ids"] if bid in cards]
        sections.append(
            TagBrowseSection(
                tag=section["tag"],
                label=TAG_LABELS.get(section["tag"], section["tag"]),
                label_hans=TAG_LABELS_HANS.get(section["tag"], section["tag"]),
                category=section["category"],
                book_count=section["book_count"],
                books=books,
            )
        )

    return sections


class _Place(NamedTuple):
    """Where a book stands in the list: how many come before it, and —
    when the order is one key and the id — that key and the book's own
    value of it (None when numbering every row was the only way)."""

    index: int
    key: Any = None
    value: Any = None
    book_id: uuid.UUID | None = None

    def before(self, order: str):
        tie = and_(self.key == self.value, Book.id < self.book_id)
        if order == "desc":
            # Descending, Postgres puts the books with no key first.
            return or_(self.key > self.value, self.key.is_(None), tie)
        return or_(self.key < self.value, tie)

    def from_here(self, order: str):
        tie = and_(self.key == self.value, Book.id >= self.book_id)
        if order == "desc":
            return or_(self.key < self.value, tie)
        return or_(self.key > self.value, self.key.is_(None), tie)


async def _place_in_order(
    db: AsyncSession,
    base_query,
    book_id: uuid.UUID,
    sort: str,
    order: str,
    order_by: list,
) -> _Place | None:
    """The book's place in the list in the given order (None when it is
    not in the list).

    Counted, where the order is one key and the id: the books whose key
    sorts before this book's — a walk of the key's index up to the book,
    where numbering every row of the list sorts all of it first."""
    if sort != "series_index":
        key = order_by[0].element
        found = (
            await db.execute(
                base_query.with_only_columns(key).where(Book.id == book_id)
            )
        ).first()
        if found is None:
            return None
        if found[0] is not None:
            place = _Place(0, key, found[0], book_id)
            count = await db.scalar(
                select(func.count()).select_from(
                    base_query.with_only_columns(Book.id)
                    .where(place.before(order))
                    .subquery()
                )
            )
            return place._replace(index=count or 0)
    ranked = base_query.with_only_columns(
        Book.id.label("id"),
        func.row_number().over(order_by=order_by).label("rn"),
    ).subquery()
    rank = await db.scalar(select(ranked.c.rn).where(ranked.c.id == book_id))
    return None if rank is None else _Place(rank - 1)


async def _page_at(
    db: AsyncSession, base_query, place: _Place, order: str, limit: int
) -> list[Book]:
    """The page that opens AROUND_BEFORE books ahead of the place: those
    few, read backwards from it, then the rest forwards — two short walks
    from the book, where an OFFSET walks the whole list up to it."""
    key = place.key
    backwards = (
        [key.asc(), Book.id.desc()] if order == "desc" else [key.desc(), Book.id.desc()]
    )
    forwards = [key.desc(), Book.id] if order == "desc" else [key.asc(), Book.id]
    ahead = list(
        await db.scalars(
            base_query.where(place.before(order))
            .order_by(*backwards)
            .limit(min(AROUND_BEFORE, place.index))
        )
    )
    ahead.reverse()
    # (The page is `limit` books from its start, wherever the book falls.)
    ahead = ahead[:limit]
    if len(ahead) == limit:
        return ahead
    rest = list(
        await db.scalars(
            base_query.where(place.from_here(order))
            .order_by(*forwards)
            .limit(limit - len(ahead))
        )
    )
    return ahead + rest


# How many books the page opened ``around`` a book shows before it.
AROUND_BEFORE = 20


def _list_order(sort: str, order: str) -> list:
    """The flat book list's ORDER BY — ending on Book.id, so the order is
    total and a book's place in it (``around``) is the place it is paged at."""
    sort_map = {
        "display_title": coalesce(Book.title, Book.epub_title),
        "added_at": coalesce(Book.calibre_added_at, Book.created_at),
        "series_index": coalesce(Book.series_index, Book.epub_series_index),
        "popularity_score": Book.popularity_score,
    }
    # A column of the table by its name, or the newest first: any other
    # attribute of the model (a relationship, `metadata`) is not an order.
    sort_col = sort_map.get(sort)
    if sort_col is None:
        sort_col = (
            getattr(Book, sort) if sort in Book.__table__.columns else Book.created_at
        )
    if sort == "series_index":
        series_col = coalesce(Book.series, Book.epub_series)
        if order == "desc":
            return [series_col.desc().nullslast(), sort_col.desc().nullslast(), Book.id]
        return [series_col.asc().nullslast(), sort_col.asc().nullslast(), Book.id]
    if order == "desc":
        return [sort_col.desc(), Book.id]
    return [sort_col.asc(), Book.id]


@router.get("", response_model=PaginatedBooksWithInteraction)
async def list_all_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    series: str | None = Query(None),
    format: str | None = Query(None),
    library: uuid.UUID | None = Query(None),
    ids: list[uuid.UUID] | None = Query(None, max_length=200),
    has_rating: bool = Query(False),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    around: uuid.UUID | None = Query(None),
):
    """The flat book list: one row per book, across every accessible library.

    ``library`` scopes the result to one library (404 when it does not exist,
    403 when the user is excluded from it) — a library's own page, and with
    ``series`` the series-detail page, which only shows that library's volumes
    (series identity is ``(library_id, series_key)``).

    ``ids`` narrows to the given books — the app's "downloaded" shelf, whose
    membership lives on the device; it pages the ids itself.

    ``around`` opens the page on a book instead of at ``offset``: it starts
    a few books before it (the library table keeps the book in view when its
    order changes). A book not in the list leaves ``offset`` as asked; the
    response's ``around_index`` says which happened.
    """

    if library is not None:
        await get_accessible_library(library, current_user, db)

    # Accessible book IDs (avoids DISTINCT on the main query)
    accessible_ids = accessible_book_ids_select(current_user)

    base_query = select(Book).where(Book.id.in_(accessible_ids))
    if ids:
        base_query = base_query.where(Book.id.in_(ids))

    # Apply filters. Search is applied last, below — its tier probe must
    # see the fully-filtered scope.
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
    tiered = None
    if search:
        tiered = await tiered_book_search(db, search, base_query)
        base_query = base_query.where(or_(*tiered.conditions))

    if ids or author or tag or series or format or has_rating or search:
        # Count over ids — the total needs nothing else from a book.
        count_query = select(func.count()).select_from(
            base_query.with_only_columns(Book.id).subquery()
        )
    else:
        # Nothing about the books themselves is asked: the count is of
        # their places in the libraries (a book has exactly one), without
        # reading the books table — on every page of an endless list.
        placed = accessible_ids
        if library:
            placed = placed.where(LibraryBook.library_id == library)
        count_query = select(func.count()).select_from(placed.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply sorting and pagination
    if series and sort == "created_at":
        sort = "series_index"
        order = "asc"
    if sort == "relevance" and tiered is None:
        # Nothing to be relevant to (a stale URL) — the default order.
        sort, order = "created_at", "desc"
    around_index: int | None = None
    if sort == "relevance":
        # Ranked over ids, the page's books fetched afterwards (see
        # relevance_ranked_ids). ``around`` does not apply: a search starts
        # from its best match.
        page_ids = list(
            await db.scalars(
                relevance_ranked_ids(base_query, tiered, search)
                .offset(offset)
                .limit(limit)
            )
        )
        books_by_id = {
            book.id: book
            for book in await db.scalars(select(Book).where(Book.id.in_(page_ids)))
        }
        books = [books_by_id[book_id] for book_id in page_ids]
    else:
        order_by = _list_order(sort, order)
        if around is not None:
            # The book's place in this very order, so the page can open on it.
            place = await _place_in_order(db, base_query, around, sort, order, order_by)
        if around is not None and place is not None:
            around_index = place.index
            offset = max(0, around_index - AROUND_BEFORE)
        if around is not None and place is not None and place.key is not None:
            books = await _page_at(db, base_query, place, order, limit)
        else:
            result = await db.execute(
                base_query.order_by(*order_by).offset(offset).limit(limit)
            )
            books = result.scalars().all()

    items = await book_cards(db, current_user.id, books)

    return PaginatedBooksWithInteraction(
        items=items, total=total, offset=offset, around_index=around_index
    )


@router.get("/grouped", response_model=PaginatedGrouped)
async def list_books_grouped(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    library: uuid.UUID | None = Query(None),
    sort: str = Query("added_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The grouped book list: a series is one item, editions of the same work
    are one item, every other book is its own.

    ``library`` scopes the result to one library (404 when it does not exist,
    403 when the user is excluded from it); without it the list spans every
    accessible library.
    """
    from app.services.series import list_grouped_books

    # The service does not apply the exclusion filter when scoped to one
    # library, so access to that library is settled here.
    if library is not None:
        await get_accessible_library(library, current_user, db)

    items, total = await list_grouped_books(
        db,
        current_user,
        library_id=library,
        search=search,
        author=author,
        tag=tag,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return PaginatedGrouped(items=items, total=total)


def _source_page_url(plugin_cls: type | None, ref: str | None) -> str | None:
    """Human-clickable page for a source-side ref, which may be a full
    URL or a bare ID (google volume ids, hardcover slugs) that needs the
    plugin's url_prefix to become one."""
    if not ref:
        return None
    if ref.startswith("http"):
        return ref
    prefix = getattr(plugin_cls, "url_prefix", None)
    return prefix + ref if prefix else None


@router.get("/metadata-lookup", response_model=IsbnLookupOut)
@limiter.limit("10/minute")
async def metadata_lookup(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    isbn: str | None = Query(None, min_length=5, max_length=20),
    title: str | None = Query(None, min_length=1, max_length=500),
    author: str | None = Query(None, max_length=255),
    url: str | None = Query(None, max_length=1000),
    source: str | None = Query(None, max_length=50),
    ref: str | None = Query(None, max_length=1000),
):
    """Fan the clues out to every capable enabled plugin (a pasted URL
    dispatches to its owning plugin instead) and return per-source
    results with provenance. Always 200 — empty lists mean nothing was
    found anywhere.

    (source, ref) is the pick step of the two-step search: `ref` is a
    candidate from metadata-search, echoed back verbatim, and resolves
    on its owning plugin only. It can't ride the `url` param because
    some refs are bare source-side IDs (google volume ids) that no
    url_prefix can dispatch."""
    require_upload_permission(current_user)
    app_settings = await get_all_settings(db)

    if source or ref:
        if not (source and ref):
            raise HTTPException(status_code=422, detail="source and ref go together")
        plugin_cls = metadata_registry.get_plugin_class(source)
        if plugin_cls is None:
            raise HTTPException(
                status_code=400, detail=f"Unknown metadata source: {source}"
            )
        if not metadata_registry.is_enabled(plugin_cls, app_settings):
            raise HTTPException(
                status_code=409, detail=f"{plugin_cls.name} is disabled"
            )
        if Clue.URL not in plugin_cls.accepts or not plugin_cls.url_prefix:
            raise HTTPException(
                status_code=400,
                detail=f"{plugin_cls.name} does not support candidate picks",
            )
        # The owning plugin will fetch whatever ref says — constrain it
        # to the plugin's own ID shape, bare or full-URL (the same rule
        # manual linking enforces), so it can't point anywhere else.
        id_body = plugin_cls.id_pattern.lstrip("^").rstrip("$")
        if not re.fullmatch(f"(?:{re.escape(plugin_cls.url_prefix)})?{id_body}", ref):
            raise HTTPException(
                status_code=400, detail=f"Invalid ref for {plugin_cls.name}"
            )
        # Original clues ride along: google re-runs its search with them
        # to restore the search/detail merge (TW descriptions).
        query = BookQuery(
            isbn=isbn,
            title=title,
            authors=[author] if author else [],
            url=ref,
        )
        record = await resolve_one(
            plugin_cls(app_settings), query, resolver=cached_resolve
        )
        pairs = [(plugin_cls.name, record)] if record else []
    elif not (isbn or title or url):
        raise HTTPException(
            status_code=422, detail="Provide an isbn, a title, or a url"
        )
    else:
        query = BookQuery(
            isbn=isbn,
            title=title,
            authors=[author] if author else [],
            url=url,
        )
        pairs = await lookup_all(query, app_settings, resolver=cached_resolve)

    results: list[IsbnSourceResult] = []
    covers: list[IsbnCoverCandidate] = []
    seen_cover_urls: set[str] = set()
    for name, record in pairs:
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
                    tags=record.tags or [],
                    url=_source_page_url(plugin_cls, record.source_url),
                )
            )
        if record.cover_url and record.cover_url not in seen_cover_urls:
            seen_cover_urls.add(record.cover_url)
            covers.append(
                IsbnCoverCandidate(source=name, label=label, url=record.cover_url)
            )
    return IsbnLookupOut(results=results, covers=covers)


@router.get("/metadata-search", response_model=MetadataSearchOut)
@limiter.limit("10/minute")
async def metadata_search(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    title: str = Query(..., min_length=1, max_length=500),
    author: str | None = Query(None, max_length=255),
):
    """First step of the two-step title search: raw per-source search
    hits, no fuzzy judgment — the user picks the right book and the
    frontend calls metadata-lookup with (source, ref) to fetch its full
    record. Always 200; empty means no source had candidates."""
    require_upload_permission(current_user)
    app_settings = await get_all_settings(db)
    query = BookQuery(title=title, authors=[author] if author else [])

    candidates: list[MetadataSearchCandidate] = []
    for name, cands in await search_all(query, app_settings):
        plugin_cls = metadata_registry.get_plugin_class(name)
        label = plugin_cls.label if plugin_cls else name
        for cand in cands:
            # A hit without a title can't be judged by the user.
            if not cand.title:
                continue
            candidates.append(
                MetadataSearchCandidate(
                    source=name,
                    label=label,
                    ref=cand.url,
                    title=cand.title,
                    authors=cand.authors,
                    url=_source_page_url(plugin_cls, cand.url),
                    publisher=cand.publisher,
                    published_date=cand.published_date,
                    cover_url=cand.cover_url,
                )
            )
    return MetadataSearchOut(candidates=candidates)


# Spine indices come from our own extractor enumerating a real OPF spine,
# but the dense array below is sized by the largest index — cap it so a
# pathological row can never balloon the response.
_MAX_SPINE_SECTIONS = 10_000


async def _section_weights(book_id: uuid.UUID, db: AsyncSession) -> list[int] | None:
    """Per-section text sizes, dense by spine index, from the text chunks.

    The chunks are the single source of truth — this is derived on read
    (indexed aggregate over at most a few hundred rows), never stored.
    None = extraction hasn't produced chunks (pending, or image-only book).
    """
    rows = (
        await db.execute(
            select(
                BookTextChunk.spine_index,
                func.sum(func.length(BookTextChunk.text)),
            )
            .where(
                BookTextChunk.book_id == book_id,
                BookTextChunk.spine_index < _MAX_SPINE_SECTIONS,
            )
            .group_by(BookTextChunk.spine_index)
        )
    ).all()
    if not rows:
        return None
    weights = [0] * (max(idx for idx, _ in rows) + 1)
    for idx, total in rows:
        if idx >= 0:
            weights[idx] = int(total or 0)
    return weights


@router.get("/{book_id}", response_model=BookOut)
async def get_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await get_accessible_book(book_id, current_user, db)
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
    out.section_weights = await _section_weights(book_id, db)
    return out


@router.get("/{book_id}/editions")
async def get_book_editions(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get other editions of the same Work plus the Work's primary_book_id.

    Returns {primary_book_id: null, editions: []} if the book has no Work.
    """
    book = await get_accessible_book(book_id, current_user, db)
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


def _series_key(book: Book) -> str | None:
    return (book.series or book.epub_series or "").strip().lower() or None


async def _series_neighbours(
    db: AsyncSession, books: list[Book], leaving: set[uuid.UUID]
) -> list[uuid.UUID]:
    """One book still in each series these books leave, per library —
    popularity is clustered by (library, series), so the series left
    behind is recomputed too."""
    libraries = dict(
        (
            await db.execute(
                select(LibraryBook.book_id, LibraryBook.library_id).where(
                    LibraryBook.book_id.in_([b.id for b in books])
                )
            )
        ).all()
    )
    neighbours: list[uuid.UUID] = []
    for library_id, key in {
        (libraries.get(b.id), _series_key(b)) for b in books if _series_key(b)
    }:
        query = select(Book.id).where(
            Book.id.not_in(leaving),
            func.lower(func.btrim(func.coalesce(Book.series, Book.epub_series))) == key,
        )
        if library_id is not None:
            query = query.where(
                Book.id.in_(
                    select(LibraryBook.book_id).where(
                        LibraryBook.library_id == library_id
                    )
                )
            )
        neighbour = await db.scalar(query.limit(1))
        if neighbour is not None:
            neighbours.append(neighbour)
    return neighbours


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
    )
    neighbours = (
        await _series_neighbours(db, [book], {book.id}) if series_will_change else []
    )

    for field in body.model_fields_set:
        setattr(book, field, data[field])
    await db.flush()

    if series_will_change:
        from app.services.popularity import recompute_popularity

        await recompute_popularity(db, [book.id, *neighbours])

    await db.commit()
    await db.refresh(book)
    return book


def _blank_to_none(value: str | None) -> str | None:
    return (value or "").strip() or None


async def _books_by_ids(db: AsyncSession, ids: list[uuid.UUID]) -> list[Book]:
    """The books, in the order asked; 404 naming any that do not exist."""
    found = {b.id: b for b in await db.scalars(select(Book).where(Book.id.in_(ids)))}
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Books not found: {', '.join(missing)}"
        )
    return [found[i] for i in ids]


@router.patch("/metadata", response_model=list[BookOut])
async def update_books_metadata(
    body: BookMetadataBulkUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Batch edit from the library table: the same authors, publisher or
    series for every book given, in one transaction; tags added to or
    taken off each; a title for one book (edit in place) or one per book
    (find and replace, worked out by the client, which showed the result). Like the edit page,
    this writes BeePub's overrides only — a Calibre book's Calibre data is
    left as it is — and a value that reads as the book's own stores none."""
    ids = list(dict.fromkeys(body.book_ids))
    fields = body.model_fields_set - {"book_ids"}
    indexes = body.series_indexes or {}
    if indexes and "series" not in fields:
        raise HTTPException(
            status_code=422, detail="series_indexes needs series alongside"
        )
    if set(indexes) - set(ids):
        raise HTTPException(
            status_code=422, detail="series_indexes names a book not in book_ids"
        )
    if "title" in fields and len(ids) != 1:
        raise HTTPException(
            status_code=422, detail="A title is given to one book at a time"
        )
    titles = body.titles or {}
    if set(titles) - set(ids):
        raise HTTPException(
            status_code=422, detail="titles names a book not in book_ids"
        )
    if "title" in fields and titles:
        raise HTTPException(status_code=422, detail="Give title or titles, not both")
    if any(len(t) > 500 for t in titles.values()):
        raise HTTPException(status_code=422, detail="A title is too long")
    tags_add = list(dict.fromkeys(t.strip() for t in body.tags_add or [] if t.strip()))
    tags_remove = {t.strip() for t in body.tags_remove or [] if t.strip()}
    if tags_remove & set(tags_add):
        raise HTTPException(status_code=422, detail="A tag is both added and removed")
    books = await _books_by_ids(db, ids)

    authors = (
        [a.strip() for a in body.authors or [] if a.strip()] or None
        if "authors" in fields
        else None
    )
    publisher = _blank_to_none(body.publisher)
    series = _blank_to_none(body.series)
    title = _blank_to_none(body.title)

    # Books whose shown series changes: their old series and new are both
    # recomputed for popularity.
    leaving = (
        [
            b
            for b in books
            if _series_key(b)
            != ((series or b.epub_series or "").strip().lower() or None)
        ]
        if "series" in fields
        else []
    )
    neighbours = (
        await _series_neighbours(db, leaving, {b.id for b in leaving})
        if leaving
        else []
    )

    for book in books:
        sources = dict(book.field_sources or {})
        written: dict[str, object] = {}
        # A value the book has of its own is no override: the book keeps
        # following its file (or Calibre) there.
        if "title" in fields:
            written["title"] = None if title == book.epub_title else title
        if book.id in titles:
            # Blank reads as "the book's own title again", as elsewhere.
            new_title = _blank_to_none(titles[book.id])
            written["title"] = None if new_title == book.epub_title else new_title
        if tags_add or tags_remove:
            shown = book.display_tags or []
            tags = [t for t in shown if t not in tags_remove]
            tags += [t for t in tags_add if t not in tags]
            # Untouched tags are not rewritten: a book that follows its
            # file's tags goes on following them.
            if tags != shown:
                written["tags"] = None if tags == (book.epub_tags or []) else tags
        if "authors" in fields:
            written["authors"] = (
                None if authors == (book.epub_authors or None) else authors
            )
        if "publisher" in fields:
            written["publisher"] = (
                None if publisher == book.epub_publisher else publisher
            )
        if "series" in fields:
            # The book shows its own number only under a series of its own:
            # one not given keeps the number the book shows now.
            index = (
                indexes[book.id] if book.id in indexes else book.display_series_index
            )
            if series is None or (
                series == book.epub_series and index == book.epub_series_index
            ):
                written["series"] = None
                book.series_index = None
            else:
                written["series"] = series
                book.series_index = index
        for field, value in written.items():
            setattr(book, field, value)
            # Provenance as the edit page keeps it: a typed value is manual,
            # a dropped override loses its key.
            if value is None:
                sources.pop(field, None)
            else:
                sources[field] = "manual"
        book.field_sources = sources or None
    await db.flush()

    if leaving:
        from app.services.popularity import recompute_popularity

        await recompute_popularity(db, [b.id for b in leaving] + neighbours)

    await db.commit()
    return list(
        await db.scalars(
            select(Book)
            .where(Book.id.in_(ids))
            .execution_options(populate_existing=True)
        )
    )


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_books(
    body: BookIdsRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete several books at once, all or none. Not Calibre books: the
    next sync would bring them back."""
    books = await _books_by_ids(db, list(dict.fromkeys(body.book_ids)))
    calibre = [str(b.id) for b in books if b.calibre_id is not None]
    if calibre:
        raise HTTPException(
            status_code=409,
            detail=f"Books in a Calibre library cannot be deleted: {', '.join(calibre)}",
        )
    paths = [path for b in books for path in book_files(b)]
    work_ids = {b.work_id for b in books if b.work_id}
    for book in books:
        await db.delete(book)
    if work_ids:
        from app.services.work_library import cleanup_orphan_works

        await cleanup_orphan_works(db, list(work_ids))
    # Files go after the commit: a failed commit must not leave rows
    # pointing at deleted files.
    await db.commit()
    for path in paths:
        delete_file(path)


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
    # Files are removed AFTER the commit — if the commit fails, a row
    # pointing at a deleted file would be unrecoverable.
    paths = book_files(book)
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
    book = await get_accessible_book(book_id, current_user, db)
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


async def _convertible_book(book_id: uuid.UUID, user: User, db: AsyncSession) -> Book:
    require_upload_permission(user)
    book = await get_accessible_book(book_id, user, db)
    if book.is_image_book or not book.file_path or not os.path.exists(book.file_path):
        raise HTTPException(status_code=409, detail="This book has no text to convert")
    # A Calibre library's files are Calibre's: never rewritten here.
    if book.calibre_id is not None:
        raise HTTPException(
            status_code=409, detail="Books in a Calibre library cannot be converted"
        )
    return book


def _live_highlights(book_id: uuid.UUID):
    return select(Highlight).where(
        Highlight.book_id == book_id, Highlight.deleted_at.is_(None)
    )


@router.get("/{book_id}/zh-conversion", response_model=ZhConversionPreview)
async def preview_book_zh(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """What converting the book would do: a sentence of it, piece by piece
    under both modes (none when nothing would change), and how many
    highlights — every reader's, since the file is shared — go along."""
    book = await _convertible_book(book_id, current_user, db)
    segments = await asyncio.to_thread(preview, book.file_path)
    count = await db.scalar(
        select(func.count()).select_from(_live_highlights(book.id).subquery())
    )
    return ZhConversionPreview(
        segments=[ZhConversionSegment(**vars(s)) for s in segments]
        if segments
        else None,
        highlights=count or 0,
    )


@router.post("/{book_id}/zh-conversion", response_model=BookOut)
async def convert_book_zh(
    book_id: uuid.UUID,
    body: ZhConversionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Rewrite the book's EPUB as Traditional Chinese, whatever script it
    was detected as, since the reader asked. The first conversion keeps the
    file as it was (an EPUB upload has no other copy). Highlights are
    carried over: each one's quote is cut from the converted text, so the
    reader re-finds the ones whose offsets moved."""
    book = await _convertible_book(book_id, current_user, db)
    # One conversion of a book at a time: a second request waits here, and
    # then sees what the first one did (the kept original above all).
    await db.execute(select(Book.id).where(Book.id == book.id).with_for_update())
    await db.refresh(book)
    file_path = book.file_path
    tmp_path = f"{file_path}.{uuid.uuid4().hex}.tmp"
    try:
        result = await asyncio.to_thread(convert_epub, file_path, tmp_path, body.mode)
        metadata = await asyncio.to_thread(parse_epub_metadata, tmp_path)
    except Exception:
        logger.exception("Conversion failed: %s", book.id)
        delete_file(tmp_path)
        raise HTTPException(
            status_code=400, detail="The book could not be converted"
        ) from None
    if not result.changed:
        delete_file(tmp_path)
        return book
    if not book.original_path:
        original_path = get_kept_epub_path(book.id)
        # (Never over a copy already kept: that one is the original.)
        if not os.path.exists(original_path):
            await asyncio.to_thread(shutil.copyfile, file_path, original_path)
        book.original_path = original_path
    os.replace(tmp_path, file_path)
    book.file_size = os.path.getsize(file_path)
    book.partial_md5 = await asyncio.to_thread(compute_partial_md5, file_path)
    for key in _CONVERTED_METADATA:
        setattr(book, key, metadata.get(key))
    now = datetime.now(UTC)
    book.updated_at = now
    for highlight in (await db.scalars(_live_highlights(book.id))).all():
        quote = convert_highlight(
            Quote(highlight.text, highlight.prefix, highlight.suffix),
            result,
            section_of(highlight.cfi_range, highlight.section_index),
            body.mode,
        )
        if (quote.text, quote.prefix, quote.suffix) != (
            highlight.text,
            highlight.prefix,
            highlight.suffix,
        ):
            highlight.text = quote.text
            highlight.prefix = quote.prefix
            highlight.suffix = quote.suffix
            # Devices pull highlights newer than theirs.
            highlight.updated_at = now
    # The text extracted from the file as it was — search, the companion's
    # quotes, summaries, vectors — is of the old script: extracted anew.
    await invalidate_derived_text(db, book)
    await db.commit()
    await db.refresh(book)
    extract_book_text.delay(str(book.id))
    return book


# What conversion rewrites in the package metadata.
_CONVERTED_METADATA = (
    "epub_title",
    "epub_authors",
    "epub_publisher",
    "epub_language",
    "epub_description",
    "epub_series",
    "epub_tags",
)


@router.get("/{book_id}/original")
async def get_book_original(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The file as it was uploaded, for books converted at ingest
    (format txt/mobi/azw3/cbz). /file stays the EPUB everything else reads."""
    if current_user.role != UserRole.admin and not current_user.can_download:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download permission required",
        )
    book = await get_accessible_book(book_id, current_user, db)
    if not book.original_path or not os.path.exists(book.original_path):
        raise HTTPException(status_code=404, detail="Original file not found")
    suffix = Path(book.original_path).suffix
    title = book.title or book.epub_title or "book"
    # octet-stream on purpose: a text/* type would get a charset=utf-8
    # appended, and the source may be Big5 or GBK.
    return FileResponse(
        book.original_path,
        media_type="application/octet-stream",
        filename=f"{title}{suffix}",
    )


@router.get("/{book_id}/content/{path:path}")
async def get_book_content(
    book_id: uuid.UUID,
    path: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Serve individual files from within the EPUB zip (the reader streams a book through it)."""
    book = await get_accessible_book(book_id, current_user, db)
    _require_book_file(book)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # ETag based on EPUB mtime + path. When Calibre rewrites the EPUB
    # (cover/xhtml edits), mtime advances and the ETag changes, so the
    # browser's cached copy is invalidated naturally.
    epub_mtime = int(os.path.getmtime(book.file_path))
    # (A checksum, not hash(): that one differs in every process, and
    # a restart would make every reader fetch its chapters again.)
    etag = f'"{epub_mtime:x}-{zlib.crc32(path.encode()):x}"'
    # A book's own files are another author's, served from this site's
    # address. Opened by their URL they must not become a page of the
    # site: one that runs scripts would run them as the reader signed in.
    # `sandbox` leaves anything opened that way without scripts and
    # without the site's origin; the reader, which fetches them and shows
    # them in its own frames, is not affected.
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=86400, must-revalidate",
        "Content-Security-Policy": "sandbox",
        "X-Content-Type-Options": "nosniff",
    }

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    try:
        # Zip decompression + regex rewrite are blocking CPU/disk work and
        # this endpoint fires on every chapter turn — keep it off the event
        # loop so concurrent readers don't serialize behind each other.
        data = await asyncio.to_thread(_read_epub_entry, book.file_path, path)
    except KeyError:
        raise HTTPException(status_code=404, detail="Path not found in EPUB") from None
    content_type, _ = mimetypes.guess_type(path)
    # A chapter is not sent as a page at all (the reader goes by the
    # book's own manifest, not by this header).
    if content_type is None or content_type in _DOCUMENT_TYPES:
        content_type = "application/octet-stream"

    return Response(
        content=data,
        media_type=content_type,
        headers=headers,
    )


_DOCUMENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def _read_epub_entry(file_path: str, path: str) -> bytes:
    with zipfile.ZipFile(file_path, "r") as zf:
        try:
            data = zf.read(path)
        except KeyError:
            # A book made on a case-insensitive file system may name a file
            # "style/a.css" that the zip holds as "Style/a.css".
            folded = {n.lower(): n for n in zf.namelist()}
            if path.lower() not in folded:
                raise
            data = zf.read(folded[path.lower()])

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
    book = await get_accessible_book(book_id, current_user, db)
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


@router.get("/{book_id}/pages")
async def get_book_pages(
    book_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The EPUB's spine as pages: each entry names the image the page
    shows, its pixel size and spread hint, in reading order with the
    book's page-progression direction. Image pagers read this instead of
    laying the XHTML out; /images is sorted by file name and is not it."""
    book = await get_accessible_book(book_id, current_user, db)
    _require_book_file(book)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    epub_mtime = int(os.path.getmtime(book.file_path))
    etag = f'"{epub_mtime:x}-pages"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=86400, must-revalidate",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    try:
        manifest = await asyncio.to_thread(read_page_manifest, book.file_path)
    except Exception:
        raise HTTPException(
            status_code=422, detail="Could not read the EPUB spine"
        ) from None
    return JSONResponse(content=manifest.to_dict(), headers=headers)


@router.get("/{book_id}/cover")
async def get_book_cover(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    size: Literal["full", "thumb"] = Query("full"),
):
    """The cover, for clients that cannot use the static path (the app
    sends a token, not a cookie). ``size=thumb`` is the small one the
    lists show — the full cover where a book has none yet."""
    book = await get_accessible_book(book_id, current_user, db)
    if not book.cover_path or not os.path.exists(book.cover_path):
        raise HTTPException(status_code=404, detail="Cover not found")
    if size == "thumb":
        thumbnail = cover_thumbnail_path(book.cover_path)
        if os.path.exists(thumbnail):
            return FileResponse(thumbnail, media_type="image/webp")
    return FileResponse(book.cover_path, media_type="image/jpeg")


@router.put("/{book_id}/cover", response_model=BookOut)
async def update_book_cover(
    book_id: uuid.UUID,
    body: BookCoverUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Replace the cover from an allowlisted source URL. The download
    lands in a temp file first so a failure can't destroy the cover the
    book already has."""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not cover_url_allowed(body.url):
        raise HTTPException(status_code=422, detail="cover url host is not allowed")
    dest = get_cover_path(book_id)
    tmp = f"{dest}.tmp-{uuid.uuid4().hex[:8]}"
    if not await download_cover(body.url, tmp):
        raise HTTPException(status_code=502, detail="Cover download failed")
    place_cover(tmp, dest)
    book.cover_path = dest
    # Same path as the old cover: bump the stamp the cover URL is keyed
    # on, or browsers keep showing the cached image.
    book.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(book)
    return book


@router.post("/{book_id}/cover", response_model=BookOut)
async def upload_book_cover(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    data = await file.read()
    if len(data) > MAX_COVER_DOWNLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Cover image too large")
    dest = get_cover_path(book_id)
    tmp = f"{dest}.tmp-{uuid.uuid4().hex[:8]}"
    if not save_cover_bytes(data, tmp):
        raise HTTPException(status_code=422, detail="Not a decodable image")
    place_cover(tmp, dest)
    book.cover_path = dest
    # Same path as the old cover: bump the stamp the cover URL is keyed
    # on, or browsers keep showing the cached image.
    book.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(book)
    return book


@router.post("/{book_id}/refresh")
async def refresh_book_metadata(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await get_accessible_book(book_id, current_user, db)
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

    await get_accessible_book(book_id, current_user, db)
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
    book = await get_accessible_book(book_id, current_user, db)

    series_name = book.display_series
    current_index = book.display_series_index
    if not series_name:
        return SeriesNeighborsOut()

    is_admin = current_user.role == UserRole.admin
    # "The book's series is this one", spelled so that the indexes on the
    # two columns can answer it — an equality on the coalesce of them
    # reads every book.
    in_series = or_(
        Book.series == series_name,
        and_(Book.series.is_(None), Book.epub_series == series_name),
    )
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
        in_series,
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
            in_series,
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
    await get_accessible_book(book_id, current_user, db)
    auto_tag_book.delay(str(book_id))
    return {"status": "queued"}


@router.get("/{book_id}/external", response_model=list[ExternalMetadataOut])
async def get_book_external_metadata(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await get_accessible_book(book_id, current_user, db)
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
