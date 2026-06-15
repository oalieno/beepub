"""Work-level reading status and is_favorite propagation.

Lazy on read: checks all editions in a Work for the 'best' interaction status.
Per-user: User A's status doesn't affect User B.

Status priority: read > currently_reading > did_not_finish > want_to_read > null
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.book import Book
from app.models.reading import UserBookInteraction

# Reading-status priority, highest first. A status's rank is its position in this
# list (1-based); the lower the rank, the higher the priority.
READING_STATUS_PRIORITY = [
    "read",
    "currently_reading",
    "did_not_finish",
    "want_to_read",
]


def best_reading_status_expr(reading_status_col):
    """SQLAlchemy aggregate expression for the highest-priority reading_status
    across the grouped rows.

    NULL statuses are ignored by MIN, so when no row in the group carries an
    actual reading_status the result is NULL -- it must never fall back to
    want_to_read (a favorite-only or progress-only interaction has a row but no
    status). Use under a GROUP BY. Shared by the book-list detail query and the
    work-propagation lookup so the two can't drift apart.
    """
    priority = case(
        *[
            (reading_status_col == status, rank)
            for rank, status in enumerate(READING_STATUS_PRIORITY, start=1)
        ]
    )
    return array(READING_STATUS_PRIORITY)[func.min(priority)]


async def get_work_propagated_interactions(
    db: AsyncSession,
    book_ids: list[uuid.UUID],
    user_id: uuid.UUID,
) -> dict[uuid.UUID, dict]:
    """For a list of book IDs, return work-propagated interaction data.

    Returns a dict mapping book_id -> {reading_status, is_favorite}.
    For books in a Work, the 'best' status across all editions is returned.
    For books not in a Work, the direct interaction is returned.
    """
    if not book_ids:
        return {}

    # For each requested book, gather every interacted edition in its Work (or
    # just itself if standalone) and reduce to the best status / any favorite.
    requested = (
        select(Book.id.label("requested_book_id"), Book.work_id.label("work_id"))
        .where(Book.id.in_(book_ids))
        .cte("requested_books")
    )
    sibling = aliased(Book)
    query = (
        select(
            requested.c.requested_book_id,
            best_reading_status_expr(UserBookInteraction.reading_status).label(
                "best_status"
            ),
            func.coalesce(func.bool_or(UserBookInteraction.is_favorite), False).label(
                "any_favorite"
            ),
        )
        .select_from(requested)
        .join(
            sibling,
            or_(
                and_(
                    requested.c.work_id.isnot(None),
                    sibling.work_id == requested.c.work_id,
                ),
                and_(
                    requested.c.work_id.is_(None),
                    sibling.id == requested.c.requested_book_id,
                ),
            ),
        )
        .join(
            UserBookInteraction,
            and_(
                UserBookInteraction.book_id == sibling.id,
                UserBookInteraction.user_id == user_id,
            ),
        )
        .group_by(requested.c.requested_book_id)
    )

    result = await db.execute(query)
    propagated = {}
    for requested_book_id, best_status, any_favorite in result.all():
        propagated[requested_book_id] = {
            "reading_status": best_status,
            "is_favorite": any_favorite,
        }
    return propagated


async def get_edition_count_map(
    db: AsyncSession,
    book_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """For a list of book IDs, return how many editions each Work has.

    Books not in a Work return None (not included in the map).
    """
    if not book_ids:
        return {}

    result = await db.execute(
        text("""
            SELECT b.id, wc.edition_count
            FROM books b
            JOIN (
                SELECT work_id, COUNT(*) AS edition_count
                FROM books
                WHERE work_id IS NOT NULL
                GROUP BY work_id
            ) wc ON wc.work_id = b.work_id
            WHERE b.id = ANY(:book_ids) AND b.work_id IS NOT NULL
        """),
        {"book_ids": [str(bid) for bid in book_ids]},
    )

    return {row[0]: row[1] for row in result.all()}
