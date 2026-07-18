"""External book popularity scoring from fetched metadata.

The score lives on `books.popularity_score` (int 0-100). It is recomputed
whenever inputs change: external_metadata writes, work_id changes, or
series edits. Reads happen directly from the column — no per-request CTE.

Cluster semantics: editions of the same Work and books sharing a
normalized series name inherit the MAX score across the cluster, so a
quiet edition of a famous book still surfaces as popular.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

GOODREADS_RATING_COUNT_ANCHOR = 1_000_000
READMOO_RATING_COUNT_ANCHOR = 2_000
HARDCOVER_RATING_COUNT_ANCHOR = 7_000
HARDCOVER_USERS_READ_COUNT_ANCHOR = 10_000
CORROBORATION_BOOST = 0.08


_RECOMPUTE_SQL = text("""
    WITH input_keys AS (
        -- One row per (input book, library) so the series cluster only spans a
        -- shared library: series identity is scoped per library.
        SELECT
            b.id,
            b.work_id,
            LOWER(NULLIF(BTRIM(COALESCE(b.series, b.epub_series)), '')) AS series_key,
            lb.library_id
        FROM books b
        LEFT JOIN library_books lb ON lb.book_id = b.id
        WHERE b.id = ANY(:book_ids)
    ),
    cluster AS (
        SELECT DISTINCT
            b.id,
            b.work_id,
            LOWER(NULLIF(BTRIM(COALESCE(b.series, b.epub_series)), '')) AS series_key
        FROM books b
        JOIN input_keys ik ON
            b.id = ik.id
            OR (ik.work_id IS NOT NULL AND b.work_id = ik.work_id)
            OR (
                ik.series_key IS NOT NULL
                AND LOWER(NULLIF(BTRIM(COALESCE(b.series, b.epub_series)), '')) = ik.series_key
                AND EXISTS (
                    SELECT 1 FROM library_books lbb
                    WHERE lbb.book_id = b.id AND lbb.library_id = ik.library_id
                )
            )
    ),
    per_source AS (
        SELECT
            c.id AS book_id,
            MAX(
                CASE WHEN em.source = 'goodreads' THEN
                    LEAST(100.0, LN(COALESCE(em.rating_count, 0) + 1) / LN(:goodreads_anchor + 1) * 100.0)
                ELSE 0.0 END
            ) AS gs,
            MAX(
                CASE WHEN em.source = 'readmoo' THEN
                    LEAST(100.0, LN(COALESCE(em.rating_count, 0) + 1) / LN(:readmoo_anchor + 1) * 100.0)
                ELSE 0.0 END
            ) AS rs,
            MAX(
                CASE WHEN em.source = 'hardcover' THEN
                    LEAST(
                        100.0,
                        GREATEST(
                            LN(COALESCE(em.rating_count, 0) + 1) / LN(:hardcover_rating_anchor + 1) * 100.0,
                            LN(COALESCE(em.readers_count, 0) + 1) / LN(:hardcover_read_anchor + 1) * 100.0
                        )
                    )
                ELSE 0.0 END
            ) AS hs
        FROM cluster c
        LEFT JOIN external_metadata em ON em.book_id = c.id
        GROUP BY c.id
    ),
    own_score AS (
        SELECT
            book_id,
            LEAST(
                100.0,
                GREATEST(gs, rs, hs)
                + :corroboration_boost * (gs + rs + hs - GREATEST(gs, rs, hs))
            ) AS score
        FROM per_source
    ),
    final AS (
        SELECT
            c1.id AS book_id,
            ROUND(MAX(COALESCE(os.score, 0)))::int AS score
        FROM cluster c1
        LEFT JOIN cluster c2 ON
            c2.id = c1.id
            OR (c1.work_id IS NOT NULL AND c2.work_id = c1.work_id)
            OR (
                c1.series_key IS NOT NULL AND c2.series_key = c1.series_key
                AND EXISTS (
                    SELECT 1 FROM library_books l1
                    JOIN library_books l2 ON l1.library_id = l2.library_id
                    WHERE l1.book_id = c1.id AND l2.book_id = c2.id
                )
            )
        LEFT JOIN own_score os ON os.book_id = c2.id
        GROUP BY c1.id
    )
    UPDATE books
    SET popularity_score = final.score
    FROM final
    WHERE books.id = final.book_id
      AND books.popularity_score IS DISTINCT FROM final.score
""")


async def recompute_popularity(db: AsyncSession, book_ids: list[uuid.UUID]) -> None:
    """Recompute and persist popularity_score for the given books and their
    work+series clusters. Caller is responsible for committing the session.
    """
    if not book_ids:
        return
    await db.execute(
        _RECOMPUTE_SQL,
        {
            "book_ids": [str(bid) for bid in book_ids],
            "goodreads_anchor": GOODREADS_RATING_COUNT_ANCHOR,
            "readmoo_anchor": READMOO_RATING_COUNT_ANCHOR,
            "hardcover_rating_anchor": HARDCOVER_RATING_COUNT_ANCHOR,
            "hardcover_read_anchor": HARDCOVER_USERS_READ_COUNT_ANCHOR,
            "corroboration_boost": CORROBORATION_BOOST,
        },
    )
