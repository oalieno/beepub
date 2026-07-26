"""Tiered fuzzy book search shared by web, OPDS, and MCP.

Single-token (or exact-phrase) queries widen through three tiers, each
tried only when the previous one has no hit within the caller's scope,
so an exact match never gets diluted by fuzzy noise:

1. plain ILIKE substring over the search columns (incl. tags)
2. normalized ILIKE — both sides folded through beepub_norm() (056):
   whitespace/punctuation/width-insensitive substring
3. trigram word_similarity over the normalized columns — tolerates a
   wrong or extra character; threshold tuned for despaced CJK where
   per-character trigrams make short strings noisy

Multi-token queries add a keyword cascade between phrase and fuzzy:
phrase → every-token (narrowing, e.g. 「三體 劉慈欣」 title+author) →
any-token ranked by match count (broadening — piling on keywords is
topic exploration, and matching none of them is the only real miss).

The caller passes its pre-search query (access control and other
filters already applied) so tier probes see exactly what the user can
see — a tier-1 hit the user has no access to must not mask a fuzzy
match they do have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, case, exists, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book

# word_similarity() over beepub_norm()ed strings. CJK trigrams are
# per-character, so genuine one-character-off matches score lower than
# latin-script typos do — 0.4 keeps 「明日明日又明天」→「明日明日又明日」
# while cutting unrelated titles.
FUZZY_WORD_SIMILARITY_THRESHOLD = 0.4

# beepub_norm() can fold a query down to almost nothing ("C++" → "c");
# a 1-character normalized substring would match most of the library.
MIN_NORMALIZED_QUERY_LEN = 2

MAX_QUERY_TOKENS = 8


def book_search_conditions(q: str) -> list:
    """The shared exact-substring book search filter (tier 1).

    The array columns (authors, tags) are matched through
    beepub_join_authors() — an IMMUTABLE SQL function created in
    migration 044 (it is a generic array joiner despite the name) — so
    the trigram expression indexes (044/058) apply. Keep the two in
    sync.
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
        func.beepub_join_authors(Book.tags).ilike(pattern),
        func.beepub_join_authors(Book.epub_tags).ilike(pattern),
    ]


# Normalized expressions must mirror the 056/058 index expressions
# exactly or the planner falls back to a sequential scan. No ISBN here.
def _normalized_columns() -> list:
    return [
        func.beepub_norm(Book.title),
        func.beepub_norm(Book.epub_title),
        func.beepub_norm(func.beepub_join_authors(Book.authors)),
        func.beepub_norm(func.beepub_join_authors(Book.epub_authors)),
        func.beepub_norm(Book.series),
        func.beepub_norm(Book.epub_series),
        func.beepub_norm(func.beepub_join_authors(Book.tags)),
        func.beepub_norm(func.beepub_join_authors(Book.epub_tags)),
    ]


def _substring_conditions(raw: str, norm: str | None) -> list:
    conds = book_search_conditions(raw)
    if norm:
        conds = conds + [col.like(f"%{norm}%") for col in _normalized_columns()]
    return conds


@dataclass
class TieredSearch:
    """Which conditions to filter with and how to rank them."""

    conditions: list
    # beepub_norm(q) — for relevance ranking against normalized columns.
    # None when the query folds too small to match on, or for multi-
    # token modes where a whole-phrase ranking makes no sense.
    normalized_query: str | None
    fuzzy: bool  # True when trigram matching had to kick in
    # "phrase" | "all_words" | "any_word" | "fuzzy" — which cascade
    # step produced the conditions (display/telemetry).
    mode: str = "phrase"
    # For "any_word": match-count expression to ORDER BY DESC so books
    # hitting more keywords surface first. None otherwise.
    rank: Any | None = None
    # For "any_word": the query tokens, aligned 1:1 with `conditions`,
    # so callers can report which keywords each row actually matched.
    tokens: list[str] | None = None


async def tiered_book_search(db: AsyncSession, q: str, scope: Select) -> TieredSearch:
    """Pick search conditions for ``q`` within ``scope`` (see module doc).

    ``scope`` is the caller's query with every non-search filter already
    applied. The returned conditions are meant to be attached to that
    same query via ``.where(or_(*result.conditions))``.

    The fuzzy branch sets ``pg_trgm.word_similarity_threshold`` with SET
    LOCAL, so the caller's real query must run in the same transaction
    (the normal single-session request flow).
    """
    tokens = q.split()[:MAX_QUERY_TOKENS]

    norm_q = await db.scalar(select(func.beepub_norm(q)))
    if not norm_q or len(norm_q) < MIN_NORMALIZED_QUERY_LEN:
        norm_q = None

    # The exact and normalized views are one query semantically — "this
    # text appears in the book's fields" — differing only in formatting,
    # so they are always OR-combined: an exact hit must not mask a
    # differently-formatted sibling (e.g. 「素人AV女優 青春篇」 hiding
    # 「素人 AV 女優 人妻篇」).
    phrase = _substring_conditions(q, norm_q)
    if await db.scalar(select_exists(scope, phrase)):
        return TieredSearch(phrase, norm_q, fuzzy=False, mode="phrase")

    if len(tokens) > 1:
        # Normalize every token in one round-trip (the SQL function is
        # the single source of truth — no Python twin to drift).
        norm_row = (
            await db.execute(select(*[func.beepub_norm(t) for t in tokens]))
        ).one()
        per_token = [
            or_(
                *_substring_conditions(
                    token,
                    n if n and len(n) >= MIN_NORMALIZED_QUERY_LEN else None,
                )
            )
            for token, n in zip(tokens, norm_row)
        ]

        narrowed = [and_(*per_token)]
        if await db.scalar(select_exists(scope, narrowed)):
            return TieredSearch(narrowed, None, fuzzy=False, mode="all_words")

        # Piling on keywords means "more topics", not "all required" —
        # broaden to any-token, ranked by how many tokens hit.
        if await db.scalar(select_exists(scope, per_token)):
            rank = sum(case((c, 1), else_=0) for c in per_token)
            return TieredSearch(
                per_token,
                None,
                fuzzy=False,
                mode="any_word",
                rank=rank,
                tokens=tokens,
            )
        return TieredSearch(phrase, norm_q, fuzzy=False, mode="phrase")

    if norm_q is None:
        return TieredSearch(phrase, norm_q, fuzzy=False, mode="phrase")

    # Trigram extraction only sees alphanumerics (CJK included) — "c++"
    # is a single-letter word to pg_trgm, and one letter word-similarity-
    # matches half the library. Symbols still work in the substring tier.
    if sum(ch.isalnum() for ch in norm_q) < 2:
        return TieredSearch(phrase, norm_q, fuzzy=False, mode="phrase")

    # SET doesn't take bind parameters; the value is a module constant.
    await db.execute(
        text(
            "SET LOCAL pg_trgm.word_similarity_threshold = "
            f"{FUZZY_WORD_SIMILARITY_THRESHOLD}"
        )
    )
    fuzzy = [literal(norm_q).op("<%")(col) for col in _normalized_columns()]
    if await db.scalar(select_exists(scope, fuzzy)):
        return TieredSearch(fuzzy, norm_q, fuzzy=True, mode="fuzzy")

    # Nothing matches anywhere — behave like today's empty result.
    return TieredSearch(phrase, norm_q, fuzzy=False, mode="phrase")


def select_exists(scope: Select, conditions: list):
    return select(exists(scope.where(or_(*conditions))))
