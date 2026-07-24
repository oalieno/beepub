"""Tiered fuzzy book search shared by web, OPDS, and (later) MCP.

Three tiers, widened only when the previous one has no hit within the
caller's scope, so an exact match never gets diluted by fuzzy noise:

1. plain ILIKE substring over the 7 search columns (unchanged behavior)
2. normalized ILIKE — both sides folded through beepub_norm() (056):
   whitespace/punctuation/width-insensitive substring
3. trigram word_similarity over the normalized columns — tolerates a
   wrong or extra character; threshold tuned for despaced CJK where
   per-character trigrams make short strings noisy

The caller passes its pre-search query (access control and other
filters already applied) so tier probes see exactly what the user can
see — a tier-1 hit the user has no access to must not mask a fuzzy
match they do have.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, exists, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book

# word_similarity() over beepub_norm()ed strings. CJK trigrams are
# per-character, so genuine one-character-off matches score lower than
# latin-script typos do — 0.4 keeps 「明日明日又明天」→「明日明日又明日」
# while cutting unrelated titles.
FUZZY_WORD_SIMILARITY_THRESHOLD = 0.4


def book_search_conditions(q: str) -> list:
    """The shared 7-column book search filter (tier 1, exact substring).

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


# Normalized expressions must mirror the 056 index expressions exactly
# or the planner falls back to a sequential scan. No ISBN here.
def _normalized_columns() -> list:
    return [
        func.beepub_norm(Book.title),
        func.beepub_norm(Book.epub_title),
        func.beepub_norm(func.beepub_join_authors(Book.authors)),
        func.beepub_norm(func.beepub_join_authors(Book.epub_authors)),
        func.beepub_norm(Book.series),
        func.beepub_norm(Book.epub_series),
    ]


# beepub_norm() can fold a query down to almost nothing ("C++" → "c");
# a 1-character normalized substring would match most of the library.
MIN_NORMALIZED_QUERY_LEN = 2


@dataclass
class TieredSearch:
    """Which conditions to filter with and how to rank them."""

    conditions: list
    # beepub_norm(q) — for relevance ranking against normalized columns.
    # None when the query folds too small to match on (then only the
    # exact tier applies).
    normalized_query: str | None
    fuzzy: bool  # True when trigram matching had to kick in


async def tiered_book_search(
    db: AsyncSession, q: str, scope: Select
) -> TieredSearch:
    """Exact + normalized substring matching, trigram fuzzy as fallback.

    The exact and normalized tiers are one query semantically — "this
    text appears in the book's fields" — differing only in formatting
    (whitespace, punctuation, character width), so they are always
    OR-combined: an exact hit must not mask a differently-formatted
    sibling (e.g. 「素人AV女優 青春篇」 hiding 「素人 AV 女優 人妻篇」).
    Trigram matching genuinely widens the query (wrong characters), so
    it only kicks in when the substring tiers have no hit within
    ``scope``.

    ``scope`` is the caller's query with every non-search filter already
    applied. The returned conditions are meant to be attached to that
    same query via ``.where(or_(*result.conditions))``.

    The fuzzy branch sets ``pg_trgm.word_similarity_threshold`` with SET
    LOCAL, so the caller's real query must run in the same transaction
    (the normal single-session request flow).
    """
    substring = book_search_conditions(q)

    norm_q = await db.scalar(select(func.beepub_norm(q)))
    if not norm_q or len(norm_q) < MIN_NORMALIZED_QUERY_LEN:
        norm_q = None
    if norm_q:
        substring = substring + [
            col.like(f"%{norm_q}%") for col in _normalized_columns()
        ]
    if await db.scalar(select_exists(scope, substring)) or norm_q is None:
        return TieredSearch(substring, norm_q, fuzzy=False)

    # Trigram extraction only sees alphanumerics (CJK included) — "c++"
    # is a single-letter word to pg_trgm, and one letter word-similarity-
    # matches half the library. Symbols still work in the substring tier.
    if sum(ch.isalnum() for ch in norm_q) < 2:
        return TieredSearch(substring, norm_q, fuzzy=False)

    # SET doesn't take bind parameters; the value is a module constant.
    await db.execute(
        text(
            "SET LOCAL pg_trgm.word_similarity_threshold = "
            f"{FUZZY_WORD_SIMILARITY_THRESHOLD}"
        )
    )
    fuzzy = [literal(norm_q).op("<%")(col) for col in _normalized_columns()]
    if await db.scalar(select_exists(scope, fuzzy)):
        return TieredSearch(fuzzy, norm_q, fuzzy=True)

    # Nothing matches anywhere — behave like today's empty result.
    return TieredSearch(substring, norm_q, fuzzy=False)


def select_exists(scope: Select, conditions: list):
    return select(exists(scope.where(or_(*conditions))))
