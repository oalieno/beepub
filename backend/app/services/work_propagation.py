"""Work-level reading status and is_favorite propagation.

Lazy on read: checks all editions in a Work for the 'best' interaction status.
Per-user: User A's status doesn't affect User B.

Status priority: read > currently_reading > did_not_finish > want_to_read > null
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Higher number = higher priority
STATUS_PRIORITY = {
    "read": 4,
    "currently_reading": 3,
    "did_not_finish": 2,
    "want_to_read": 1,
}


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

    # Single query: for each requested book, find the best interaction
    # across all editions in its Work (or just itself if no Work).
    result = await db.execute(
        text("""
            WITH requested_books AS (
                SELECT id, work_id FROM books WHERE id = ANY(:book_ids)
            ),
            work_siblings AS (
                -- For books in a Work: all sibling book IDs (including self)
                -- For books not in a Work: just the book itself
                SELECT rb.id AS requested_book_id, sibling.id AS sibling_book_id
                FROM requested_books rb
                JOIN books sibling ON (
                    CASE
                        WHEN rb.work_id IS NOT NULL THEN sibling.work_id = rb.work_id
                        ELSE sibling.id = rb.id
                    END
                )
            ),
            sibling_interactions AS (
                SELECT
                    ws.requested_book_id,
                    ubi.reading_status,
                    ubi.is_favorite
                FROM work_siblings ws
                JOIN user_book_interactions ubi ON ubi.book_id = ws.sibling_book_id
                WHERE ubi.user_id = :user_id
            )
            SELECT
                requested_book_id,
                -- Best reading status (by priority)
                (ARRAY['read','currently_reading','did_not_finish','want_to_read'])[
                    LEAST(
                        COALESCE(MIN(CASE reading_status
                            WHEN 'read' THEN 1
                            WHEN 'currently_reading' THEN 2
                            WHEN 'did_not_finish' THEN 3
                            WHEN 'want_to_read' THEN 4
                        END), 99),
                        4
                    )
                ] AS best_status,
                -- is_favorite: true if ANY sibling is favorited
                COALESCE(BOOL_OR(is_favorite), false) AS any_favorite
            FROM sibling_interactions
            GROUP BY requested_book_id
        """),
        {"book_ids": [str(bid) for bid in book_ids], "user_id": str(user_id)},
    )

    propagated = {}
    for row in result.all():
        propagated[row[0]] = {
            "reading_status": row[1] if row[1] != 99 else None,
            "is_favorite": row[2],
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
