"""Series aggregation — series have no entity table, they are grouped by the
normalised series name (the same key popularity/recommendations use).

A per-user `user_series_interactions` row hangs rating/notes off that key. A
series rating is independent of its volumes' ratings: rating a single volume
never changes the series rating, and vice versa.
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
    keys: list[str] | None = None,
    search: str | None = None,
    rated_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Aggregate series with the user's rating/notes. Returns (rows, total).

    - library_id: restrict to one library (access must be checked by caller).
    - key: a single series_key (the series-detail page).
    - keys: a set of series_keys (the collapsed feed hydrates its page this way).
    - search: case-insensitive series-name filter.
    - rated_only: only series the user rated explicitly — used by the tier
      page across all accessible libraries.
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
    if keys is not None:
        # Empty set → no rows (avoids a malformed `= ANY('{}')` matching nothing
        # ambiguously); callers should skip the query when there are no keys.
        filters.append("joined.series_key = ANY(:keys)")
        params["keys"] = keys
    if search:
        filters.append("joined.series_name ILIKE :search")
        params["search"] = f"%{search}%"
    if rated_only:
        filters.append("joined.series_rating IS NOT NULL")
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
                    usi.notes AS series_notes
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
        rows.append(
            {
                "series_key": r["series_key"],
                "series_name": r["series_name"],
                "book_count": r["book_count"],
                "read_count": r["read_count"],
                "cover_book_id": r["cover_book_id"],
                "rating": float(explicit) if explicit is not None else None,
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
            notes=r["notes"],
            cover_book=covers.get(r["cover_book_id"]),
        )
        for r in rows
    ]


# Sort param -> the unit column it maps to in the feed ordering query.
_FEED_ORD_COLUMNS = {
    "display_title": "ord_title",
    "added_at": "ord_added",
    "popularity_score": "ord_pop",
}


async def list_library_feed(
    db: AsyncSession,
    user: User,
    *,
    library_id: uuid.UUID | None = None,
    search: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    sort: str = "added_at",
    order: str = "desc",
    limit: int = 60,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """The collapsed library view: a single ordered, paginated feed where each
    series collapses to one unit and series-less books stay individual.

    Returns ``(items, total)`` where each item is one of:
      - ``{"type": "series", "series": SeriesOut}``
      - ``{"type": "book", "book_id": uuid}``  (the caller hydrates books)

    Membership is filtered by search/author/tag against the underlying volumes;
    a series surfaces when any of its volumes matches. Series cards still show
    the whole series (counts/cover come from :func:`list_series`).
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
    if search:
        params["search"] = f"%{search}%"
        filters.append(
            "("
            "coalesce(b.title, '') ILIKE :search"
            " OR coalesce(b.epub_title, '') ILIKE :search"
            " OR coalesce(b.authors::text, '') ILIKE :search"
            " OR coalesce(b.epub_authors::text, '') ILIKE :search"
            " OR coalesce(b.series, '') ILIKE :search"
            " OR coalesce(b.epub_series, '') ILIKE :search"
            " OR coalesce(b.epub_isbn, '') ILIKE :search"
            ")"
        )
    if author:
        params["author"] = author
        filters.append("(:author = ANY(b.authors) OR :author = ANY(b.epub_authors))")
    if tag:
        params["tag"] = tag
        filters.append(
            "(:tag = ANY(b.tags) OR :tag = ANY(b.epub_tags)"
            " OR b.id IN (SELECT book_id FROM book_tags WHERE tag = :tag))"
        )
    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    ord_col = _FEED_ORD_COLUMNS.get(sort, "ord_added")
    direction = "DESC" if order == "desc" else "ASC"

    params["limit"] = limit
    params["offset"] = offset

    result = await db.execute(
        text(f"""
            WITH accessible AS ({accessible}),
            eligible AS (
                SELECT
                    b.id AS book_id,
                    lower(btrim(coalesce(b.series, b.epub_series))) AS series_key,
                    coalesce(b.title, b.epub_title) AS display_title,
                    coalesce(b.calibre_added_at, b.created_at) AS added_at,
                    b.popularity_score AS popularity_score
                FROM books b
                JOIN accessible a ON a.book_id = b.id
                {where}
            ),
            units AS (
                SELECT
                    'series' AS kind,
                    series_key,
                    NULL::uuid AS book_id,
                    max(display_title) AS ord_title,
                    max(added_at) AS ord_added,
                    max(popularity_score) AS ord_pop
                FROM eligible
                WHERE series_key IS NOT NULL
                GROUP BY series_key
                UNION ALL
                SELECT
                    'book' AS kind,
                    NULL::text AS series_key,
                    book_id,
                    display_title AS ord_title,
                    added_at AS ord_added,
                    popularity_score AS ord_pop
                FROM eligible
                WHERE series_key IS NULL
            )
            SELECT kind, series_key, book_id, count(*) OVER () AS total_count
            FROM units
            ORDER BY {ord_col} {direction} NULLS LAST,
                     ord_title ASC, kind, series_key, book_id
            LIMIT :limit OFFSET :offset
        """),
        params,
    )

    page = list(result.mappings())
    total = page[0]["total_count"] if page else 0

    series_keys = [r["series_key"] for r in page if r["kind"] == "series"]
    series_by_key: dict = {}
    if series_keys:
        rows, _ = await list_series(db, user, library_id=library_id, keys=series_keys)
        out = await build_series_out(db, rows)
        series_by_key = {s.series_key: s for s in out}

    book_ids = [r["book_id"] for r in page if r["kind"] == "book"]
    book_by_id = await _hydrate_feed_books(db, user, book_ids)

    items: list[dict] = []
    for r in page:
        if r["kind"] == "series":
            series = series_by_key.get(r["series_key"])
            if series is not None:
                items.append({"type": "series", "series": series})
        else:
            book = book_by_id.get(r["book_id"])
            if book is not None:
                items.append({"type": "book", "book": book})
    return items, total


async def _hydrate_feed_books(db: AsyncSession, user: User, book_ids: list) -> dict:
    """Load standalone feed books into BookWithInteractionOut keyed by id, with
    the same edition-count + work-propagated interaction enrichment the book
    listing endpoints apply."""
    from app.models.book import Book
    from app.models.reading import UserBookInteraction
    from app.schemas.book import BookWithInteractionOut
    from app.services.work_propagation import (
        get_edition_count_map,
        get_work_propagated_interactions,
    )

    if not book_ids:
        return {}

    books = (
        (await db.execute(select(Book).where(Book.id.in_(book_ids)))).scalars().all()
    )
    edition_counts = await get_edition_count_map(db, book_ids)
    propagated = await get_work_propagated_interactions(db, book_ids, user.id)
    ratings_result = await db.execute(
        select(UserBookInteraction.book_id, UserBookInteraction.rating).where(
            UserBookInteraction.user_id == user.id,
            UserBookInteraction.book_id.in_(book_ids),
            UserBookInteraction.rating.is_not(None),
        )
    )
    ratings_map = {row[0]: row[1] for row in ratings_result.all()}

    result: dict = {}
    for b in books:
        item = BookWithInteractionOut.model_validate(b)
        item.edition_count = edition_counts.get(b.id)
        item.user_rating = ratings_map.get(b.id)
        prop = propagated.get(b.id)
        if prop:
            item.reading_status = prop["reading_status"]
            item.is_favorite = prop["is_favorite"]
        result[b.id] = item
    return result
