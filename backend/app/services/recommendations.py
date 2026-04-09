"""Recommendation engine: similar books and personalized suggestions."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_similar_books(
    db: AsyncSession,
    book_id: uuid.UUID,
    user_id: uuid.UUID,
    is_admin: bool,
    limit: int = 10,
    semantic_weight: float | None = None,
    semantic_limit: int | None = None,
) -> list[dict]:
    """Return books similar to the given book, respecting user access.

    Scoring (metadata signals):
    - AI tag overlap: +3 per shared tag
    - Manual/epub tag overlap: +3 per shared tag
    - Author overlap: +5 per shared author
    - Same publisher: +2
    - Same language: +1
    - Library co-occurrence: +1 per shared library

    Scoring (semantic signal):
    - Cosine similarity × semantic_weight (default 10.0)

    Returns list of dicts with book_id, score, and cosine_similarity (if available).
    """
    if semantic_weight is None:
        from app.services.settings import get_all_settings

        settings = await get_all_settings(db)
        semantic_weight = float(settings.get("similar_books_semantic_weight", "10.0"))
        semantic_limit = int(settings.get("similar_books_semantic_limit", "50"))
    if semantic_limit is None:
        semantic_limit = 50

    # Get total book count for IDF weighting
    total_books_result = await db.execute(text("SELECT COUNT(*) FROM books"))
    total_books = total_books_result.scalar() or 1

    # Two-phase approach for large libraries:
    # 1. Gather candidates via indexed lookups (only books sharing a signal)
    # 2. Score only those candidates
    #
    # Semantic similarity architecture:
    #   book_embeddings (one 1024-dim vector per book)
    #       │
    #       ▼ CROSS JOIN LATERAL (HNSW ANN scan)
    #   semantic_candidates CTE → cosine similarity × weight → all_scores UNION ALL
    query = text("""
        WITH target AS (
            SELECT
                id,
                COALESCE(authors, epub_authors, '{}') AS t_authors,
                COALESCE(publisher, epub_publisher) AS t_publisher,
                epub_language AS t_language,
                COALESCE(tags, epub_tags, '{}') AS t_tags
            FROM books WHERE id = :book_id
        ),
        accessible_libs AS (
            SELECT l.id AS library_id
            FROM libraries l
            WHERE :is_admin = true
               OR l.id NOT IN (
                   SELECT library_id FROM user_library_exclusions WHERE user_id = :user_id
               )
        ),
        -- Phase 1: gather candidate book IDs via indexed lookups
        -- Author overlap (uses GIN index on authors arrays)
        author_candidates AS (
            SELECT b.id AS book_id, 5 AS score
            FROM books b, target t
            WHERE b.id != :book_id
              AND COALESCE(b.authors, b.epub_authors, '{}')
                  && t.t_authors
        ),
        -- Tag overlap (uses GIN index on tags arrays)
        tag_candidates AS (
            SELECT b.id AS book_id, 3 AS score
            FROM books b, target t
            WHERE b.id != :book_id
              AND COALESCE(b.tags, b.epub_tags, '{}')
                  && t.t_tags
        ),
        -- Tag overlap with IDF weighting + category multipliers
        -- Rare tags (hard sci-fi) score much higher than common tags (literary fiction)
        -- Tropes 3x, subgenre/theme 2x, mood 1.5x, genre 1x
        tag_idf AS (
            SELECT tag, COUNT(DISTINCT book_id) AS doc_count
            FROM book_tags GROUP BY tag
        ),
        book_tag_candidates AS (
            SELECT b_tags.book_id,
                   SUM(
                       LN(GREATEST(CAST(:total_books AS float), 1) / GREATEST(ti.doc_count, 1))
                       * CASE b_tags.category::text
                           WHEN 'trope' THEN 3.0
                           WHEN 'subgenre' THEN 2.0
                           WHEN 'theme' THEN 2.0
                           WHEN 'mood' THEN 1.5
                           ELSE 1.0
                         END
                   ) AS score
            FROM book_tags t_tags
            JOIN book_tags b_tags ON t_tags.tag = b_tags.tag
            JOIN tag_idf ti ON ti.tag = t_tags.tag
            WHERE t_tags.book_id = :book_id
              AND b_tags.book_id != :book_id
            GROUP BY b_tags.book_id
        ),
        -- Same publisher
        publisher_candidates AS (
            SELECT b.id AS book_id, 2 AS score
            FROM books b, target t
            WHERE b.id != :book_id
              AND t.t_publisher IS NOT NULL
              AND COALESCE(b.publisher, b.epub_publisher) = t.t_publisher
        ),
        -- Same language
        language_candidates AS (
            SELECT b.id AS book_id, 1 AS score
            FROM books b, target t
            WHERE b.id != :book_id
              AND t.t_language IS NOT NULL
              AND b.epub_language = t.t_language
        ),
        -- Library co-occurrence
        lib_candidates AS (
            SELECT lb2.book_id, COUNT(DISTINCT lb2.library_id) AS score
            FROM library_books lb1
            JOIN library_books lb2 ON lb1.library_id = lb2.library_id
            WHERE lb1.book_id = :book_id
              AND lb2.book_id != :book_id
            GROUP BY lb2.book_id
        ),
        -- Semantic similarity (cosine distance on book-level summary embeddings)
        -- Returns empty if the target book has no embedding (graceful degradation)
        semantic_candidates AS (
            SELECT bse2.book_id,
                   (1 - (bse1.embedding <=> bse2.embedding)) * :semantic_weight AS score,
                   (1 - (bse1.embedding <=> bse2.embedding)) AS cosine_sim
            FROM book_embeddings bse1
            CROSS JOIN LATERAL (
                SELECT book_id, embedding FROM book_embeddings
                WHERE book_id != :book_id
                ORDER BY embedding <=> bse1.embedding
                LIMIT :semantic_limit
            ) bse2
            WHERE bse1.book_id = :book_id
        ),
        -- Phase 2: union all scores, filter to accessible, aggregate
        all_scores AS (
            SELECT book_id, score FROM author_candidates
            UNION ALL
            SELECT book_id, score FROM tag_candidates
            UNION ALL
            SELECT book_id, score FROM book_tag_candidates
            UNION ALL
            SELECT book_id, score FROM publisher_candidates
            UNION ALL
            SELECT book_id, score FROM language_candidates
            UNION ALL
            SELECT book_id, score FROM lib_candidates
            UNION ALL
            SELECT book_id, score FROM semantic_candidates
        ),
        -- Exclude same-work editions (different editions of the target book)
        target_work AS (
            SELECT work_id FROM books WHERE id = :book_id AND work_id IS NOT NULL
        ),
        aggregated AS (
            SELECT a.book_id, SUM(a.score) AS total_score
            FROM all_scores a
            WHERE a.book_id IN (
                SELECT lb.book_id FROM library_books lb
                WHERE lb.library_id IN (SELECT library_id FROM accessible_libs)
            )
            AND NOT EXISTS (
                SELECT 1 FROM target_work tw
                JOIN books b ON b.work_id = tw.work_id
                WHERE b.id = a.book_id
            )
            GROUP BY a.book_id
        )
        SELECT
            aggregated.book_id,
            aggregated.total_score,
            semantic_candidates.cosine_sim
        FROM aggregated
        LEFT JOIN semantic_candidates ON aggregated.book_id = semantic_candidates.book_id
        ORDER BY aggregated.total_score DESC
        LIMIT :limit
    """)

    result = await db.execute(
        query,
        {
            "book_id": str(book_id),
            "user_id": str(user_id),
            "is_admin": is_admin,
            "limit": limit,
            "total_books": total_books,
            "semantic_weight": semantic_weight,
            "semantic_limit": semantic_limit,
        },
    )
    return [
        {
            "book_id": uuid.UUID(str(row[0])),
            "score": row[1],
            "cosine_similarity": float(row[2]) if row[2] is not None else None,
        }
        for row in result.fetchall()
    ]


async def get_personalized_recommendations(
    db: AsyncSession,
    user_id: uuid.UUID,
    is_admin: bool,
    limit: int = 20,
) -> list[dict]:
    """Personalized recommendations based on user's favorites and highly-rated books."""
    # Get seed books: favorites, books with reading activity, or highly-rated.
    # Exclude only books explicitly rated < 4 (no rating = no opinion = include).
    seed_result = await db.execute(
        text("""
            SELECT book_id FROM user_book_interactions
            WHERE user_id = :user_id
              AND (
                  is_favorite = true
                  OR reading_status IN ('read', 'currently_reading', 'want_to_read')
                  OR rating >= 4
              )
              AND (rating IS NULL OR rating >= 4)
            ORDER BY updated_at DESC
            LIMIT 10
        """),
        {"user_id": str(user_id)},
    )
    seed_book_ids = [row[0] for row in seed_result.fetchall()]

    if not seed_book_ids:
        return []

    # Get similar books for each seed, aggregate scores
    # Track (total_score, best_seed_id, best_seed_contribution) per candidate
    all_scores: dict[uuid.UUID, tuple[float, uuid.UUID, float]] = {}
    for seed_id in seed_book_ids:
        sid = uuid.UUID(str(seed_id))
        similar = await get_similar_books(db, sid, user_id, is_admin, limit=20)
        for item in similar:
            bid = item["book_id"]
            score = item["score"]
            if bid in all_scores:
                prev_total, prev_seed, prev_contrib = all_scores[bid]
                new_total = prev_total + score
                # Keep the seed with the highest contribution
                if score > prev_contrib:
                    all_scores[bid] = (new_total, sid, score)
                else:
                    all_scores[bid] = (new_total, prev_seed, prev_contrib)
            else:
                all_scores[bid] = (score, sid, score)

    # Remove books user has already interacted with (read, reading, want to read),
    # AND books that share a work_id or series with those books (same-work/series dedup)
    interacted_result = await db.execute(
        text("""
            SELECT book_id FROM user_book_interactions
            WHERE user_id = :user_id
              AND (
                  reading_status IN ('read', 'currently_reading', 'want_to_read')
                  OR is_favorite = true
              )
        """),
        {"user_id": str(user_id)},
    )
    interacted_ids = {uuid.UUID(str(row[0])) for row in interacted_result.fetchall()}

    # Also remove seed books themselves
    exclude_ids = interacted_ids | {uuid.UUID(str(sid)) for sid in seed_book_ids}

    # Exclude books sharing a work_id with any excluded book
    if exclude_ids:
        work_sibling_result = await db.execute(
            text("""
                SELECT b2.id
                FROM books b1
                JOIN books b2 ON b2.work_id = b1.work_id AND b2.id != b1.id
                WHERE b1.id = ANY(:exclude_ids) AND b1.work_id IS NOT NULL
            """),
            {"exclude_ids": [str(eid) for eid in exclude_ids]},
        )
        work_siblings = {
            uuid.UUID(str(row[0])) for row in work_sibling_result.fetchall()
        }
        exclude_ids = exclude_ids | work_siblings

    # Get series names for excluded books to also exclude same-series books
    exclude_series_result = await db.execute(
        text("""
            SELECT DISTINCT COALESCE(series, epub_series)
            FROM books
            WHERE id = ANY(:exclude_ids)
              AND COALESCE(series, epub_series) IS NOT NULL
        """),
        {"exclude_ids": [str(eid) for eid in exclude_ids]},
    )
    exclude_series = {row[0] for row in exclude_series_result.fetchall()}

    # Get series info for all candidate books (for dedup)
    candidate_ids = [bid for bid in all_scores if bid not in exclude_ids]
    candidate_series: dict[uuid.UUID, str | None] = {}
    if candidate_ids:
        series_result = await db.execute(
            text("""
                SELECT id, COALESCE(series, epub_series) AS series_name
                FROM books
                WHERE id = ANY(:ids)
            """),
            {"ids": [str(cid) for cid in candidate_ids]},
        )
        for row in series_result.fetchall():
            candidate_series[uuid.UUID(str(row[0]))] = row[1]

    filtered = []
    seen_series: set[str] = set()
    # Sort by score first so we keep the highest-scoring book per series
    sorted_candidates = sorted(all_scores.items(), key=lambda x: x[1][0], reverse=True)
    for bid, (total, seed_id, _) in sorted_candidates:
        if bid in exclude_ids:
            continue
        series_name = candidate_series.get(bid)
        # Skip if this book's series is in the excluded set
        if series_name and series_name in exclude_series:
            continue
        # Keep only one book per series
        if series_name:
            if series_name in seen_series:
                continue
            seen_series.add(series_name)
        filtered.append(
            {
                "book_id": bid,
                "score": total,
                "seed_book_id": seed_id,
            }
        )
        if len(filtered) >= limit:
            break

    return filtered


async def get_books_by_tag_category(
    db: AsyncSession,
    user_id: uuid.UUID,
    is_admin: bool,
    category: str,
    limit_per_tag: int = 8,
    max_tags: int = 10,
) -> list[dict]:
    """Return popular tags in a category with sample books for each."""
    # Get top tags by book count in category
    tags_result = await db.execute(
        text("""
            SELECT at.tag, COUNT(DISTINCT at.book_id) as book_count
            FROM book_tags at
            JOIN library_books lb ON lb.book_id = at.book_id
            JOIN libraries l ON l.id = lb.library_id
            WHERE at.category = :category
              AND (
                  :is_admin = true
                  OR l.id NOT IN (
                      SELECT library_id FROM user_library_exclusions WHERE user_id = :user_id
                  )
              )
            GROUP BY at.tag
            HAVING COUNT(DISTINCT at.book_id) >= 2
            ORDER BY book_count DESC
            LIMIT :max_tags
        """),
        {
            "category": category,
            "user_id": str(user_id),
            "is_admin": is_admin,
            "max_tags": max_tags,
        },
    )
    tags = tags_result.fetchall()

    sections = []
    for tag_row in tags:
        tag_name = tag_row[0]
        book_count = tag_row[1]

        # Get sample books for this tag
        books_result = await db.execute(
            text("""
                SELECT b.id
                FROM books b
                JOIN book_tags at ON at.book_id = b.id
                JOIN library_books lb ON lb.book_id = b.id
                JOIN libraries l ON l.id = lb.library_id
                WHERE at.tag = :tag
                  AND at.category = :category
                  AND (
                      :is_admin = true
                      OR l.id NOT IN (
                          SELECT library_id FROM user_library_exclusions WHERE user_id = :user_id
                      )
                  )
                GROUP BY b.id
                ORDER BY MAX(at.confidence) DESC
                LIMIT :limit_per_tag
            """),
            {
                "tag": tag_name,
                "category": category,
                "user_id": str(user_id),
                "is_admin": is_admin,
                "limit_per_tag": limit_per_tag,
            },
        )
        book_ids = [uuid.UUID(str(row[0])) for row in books_result.fetchall()]
        sections.append(
            {
                "tag": tag_name,
                "category": category,
                "book_count": book_count,
                "book_ids": book_ids,
            }
        )

    return sections
