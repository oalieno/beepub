"""What a reader has read: the activity calendar, the yearly numbers and
goal, and the list of the books they have a status for.

Same ``/api/books`` prefix as the rest (the URLs predate the split), and
registered before ``books.router``: these paths are fixed words where
that router has ``/{book_id}``.
"""

import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import coalesce

from app import errors
from app.database import get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.library import Library, LibraryBook
from app.models.reading import ReadingActivity, UserBookInteraction
from app.models.user import User
from app.schemas.book import (
    PaginatedBooksWithInteraction,
)
from app.schemas.reading import (
    ReadingActivityOut,
    ReadingGoalUpdate,
    ReadingStatsOut,
)
from app.services.access import (
    accessible_libraries_condition,
)
from app.services.book_cards import book_cards
from app.services.settings import today_in_app_timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


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
    today = await today_in_app_timezone(db)

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
        raise errors.GOAL_OUT_OF_RANGE()

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
