"""Series aggregation — series have no entity table, they are grouped by the
normalised series name (the same key popularity/recommendations use).

A per-user `user_series_interactions` row hangs rating/notes off that key. The
"effective" rating falls back to the best-rated volume so a user's existing
"rate volume 1" habit surfaces at the series level without a backfill.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


def normalize_series_name(name: str | None) -> str | None:
    """Match the SQL key: lower(btrim(coalesce(series, epub_series))) or NULL."""
    if not name:
        return None
    key = name.strip().lower()
    return key or None


async def list_series(
    db: AsyncSession,
    user: User,
    *,
    library_id: uuid.UUID | None = None,
    key: str | None = None,
    search: str | None = None,
    rated_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Aggregate series with the user's rating/notes. Returns (rows, total).

    - library_id: restrict to one library (access must be checked by caller).
    - search: case-insensitive series-name filter.
    - rated_only: only series with an effective rating (explicit or a rated
      volume) — used by the tier page across all accessible libraries.
    - limit/offset: page the result; omit limit to return everything.
    """
    params: dict = {"uid": str(user.id)}

    if library_id is not None:
        accessible = (
            "SELECT lb.book_id FROM library_books lb WHERE lb.library_id = :lib"
        )
        params["lib"] = str(library_id)
    elif user.role == UserRole.admin:
        accessible = "SELECT lb.book_id FROM library_books lb"
    else:
        accessible = """
            SELECT lb.book_id
            FROM library_books lb
            JOIN libraries l ON l.id = lb.library_id
            WHERE NOT EXISTS (
                SELECT 1 FROM user_library_exclusions ule
                WHERE ule.user_id = :uid AND ule.library_id = l.id
            )
        """

    filters = []
    if key:
        filters.append("joined.series_key = :key")
        params["key"] = key
    if search:
        filters.append("joined.series_name ILIKE :search")
        params["search"] = f"%{search}%"
    if rated_only:
        filters.append("joined.effective IS NOT NULL")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    page_clause = ""
    if limit is not None:
        page_clause = "LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset

    result = await db.execute(
        text(f"""
            WITH accessible AS ({accessible}),
            series_books AS (
                SELECT
                    b.id AS book_id,
                    lower(btrim(coalesce(b.series, b.epub_series))) AS series_key,
                    coalesce(b.series, b.epub_series) AS series_name,
                    coalesce(b.series_index, b.epub_series_index) AS idx,
                    b.created_at AS created_at,
                    ubi.rating AS vol_rating,
                    ubi.reading_status AS reading_status
                FROM books b
                JOIN accessible a ON a.book_id = b.id
                LEFT JOIN user_book_interactions ubi
                    ON ubi.book_id = b.id AND ubi.user_id = :uid
                WHERE nullif(btrim(coalesce(b.series, b.epub_series)), '') IS NOT NULL
            ),
            agg AS (
                SELECT
                    series_key,
                    max(series_name) AS series_name,
                    count(*) AS book_count,
                    count(*) FILTER (WHERE reading_status = 'read') AS read_count,
                    max(vol_rating) AS max_vol_rating,
                    (array_agg(book_id ORDER BY idx ASC NULLS LAST, created_at ASC))[1]
                        AS cover_book_id
                FROM series_books
                GROUP BY series_key
            ),
            joined AS (
                SELECT
                    agg.series_key,
                    agg.series_name,
                    agg.book_count,
                    agg.read_count,
                    agg.cover_book_id,
                    usi.rating AS series_rating,
                    usi.notes AS series_notes,
                    coalesce(usi.rating, agg.max_vol_rating) AS effective
                FROM agg
                LEFT JOIN user_series_interactions usi
                    ON usi.user_id = :uid AND usi.series_key = agg.series_key
            )
            SELECT joined.*, count(*) OVER () AS total_count
            FROM joined
            {where}
            ORDER BY joined.series_name
            {page_clause}
        """),
        params,
    )

    rows = []
    total = 0
    for r in result.mappings():
        total = r["total_count"]
        explicit = r["series_rating"]
        eff = r["effective"]
        rows.append(
            {
                "series_key": r["series_key"],
                "series_name": r["series_name"],
                "book_count": r["book_count"],
                "read_count": r["read_count"],
                "cover_book_id": r["cover_book_id"],
                "rating": float(explicit) if explicit is not None else None,
                "effective_rating": float(eff) if eff is not None else None,
                "notes": r["series_notes"],
            }
        )
    return rows, total


async def build_series_out(db: AsyncSession, rows: list[dict]) -> list:
    """Attach cover books (one query) and return a list of SeriesOut."""
    from app.models.book import Book
    from app.schemas.book import BookOut
    from app.schemas.series import SeriesOut

    cover_ids = [r["cover_book_id"] for r in rows if r["cover_book_id"]]
    covers: dict = {}
    if cover_ids:
        books = (
            (await db.execute(select(Book).where(Book.id.in_(cover_ids))))
            .scalars()
            .all()
        )
        covers = {b.id: BookOut.model_validate(b) for b in books}

    return [
        SeriesOut(
            series_key=r["series_key"],
            series_name=r["series_name"],
            book_count=r["book_count"],
            read_count=r["read_count"],
            rating=r["rating"],
            effective_rating=r["effective_rating"],
            notes=r["notes"],
            cover_book=covers.get(r["cover_book_id"]),
        )
        for r in rows
    ]
