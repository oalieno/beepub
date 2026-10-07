"""Tiered fuzzy book search shared by web, OPDS, and MCP.

Single-token (or exact-phrase) queries widen through three tiers, each
tried only when the previous one has no hit within the caller's scope,
so an exact match never gets diluted by fuzzy noise:

1. plain ILIKE substring over the search columns (incl. tags)
2. normalized LIKE — the query folded through beepub_norm() (056),
   the columns read from their stored folded copy (065):
   whitespace/punctuation/width/script-insensitive substring
   (1 and 2 are one step; when the query folds to something usable,
   2 contains every hit of 1 and runs alone — see _substring_conditions)
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

from sqlalchemy import (
    Select,
    and_,
    case,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book

# word_similarity() over beepub_norm()ed strings. CJK trigrams are
# per-character, so genuine one-character-off matches score lower than
# latin-script typos do — 0.4 keeps 「明日明日又明天」→「明日明日又明日」
# while cutting unrelated titles.
FUZZY_WORD_SIMILARITY_THRESHOLD = 0.4

# beepub_norm() can fold a query down to almost nothing ("C++" → "c");
# a 1-character normalized substring would match most of the library.
# A query that was one character to begin with is searched as asked.
MIN_NORMALIZED_QUERY_LEN = 2

# Fewer alphanumerics than this and the fuzzy tier cannot find anything
# the substring tiers did not (see tiered_book_search).
MIN_FUZZY_QUERY_CHARS = 3

MAX_QUERY_TOKENS = 8


def _no_match() -> list:
    """What a search that matched nothing filters with: the probes
    already know the answer, so the caller's count and page queries
    read no rows."""
    return [false()]


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


# Folded text is read from stored generated columns (065), never
# computed while searching: beepub_norm() costs ~0.3 ms per title since
# it folds Chinese scripts (064), and a pattern shorter than a trigram —
# any two-character Chinese word — is answered by reading every row.
#
# One column per search field, trigram-indexed, for the fuzzy tier. No
# ISBN here.
def _normalized_columns() -> list:
    return [
        Book.title_norm,
        Book.epub_title_norm,
        Book.authors_norm,
        Book.epub_authors_norm,
        Book.series_norm,
        Book.epub_series_norm,
        Book.tags_norm,
        Book.epub_tags_norm,
    ]


def normalized_title():
    """beepub_norm() of the displayed title, from the stored columns.

    beepub_norm() is strict, so coalescing the folded columns equals
    folding the coalesced one.
    """
    return func.coalesce(Book.title_norm, Book.epub_title_norm)


def normalized_series():
    return func.coalesce(Book.series_norm, Book.epub_series_norm)


def _usable_fold(raw: str, norm: str | None) -> str | None:
    """The folded query, or None when the fold left too little of it."""
    if not norm:
        return None
    if len(norm) >= MIN_NORMALIZED_QUERY_LEN:
        return norm
    # Folding dropped nothing (it only maps, or lowercases): 「的」, "a".
    return norm if len("".join(raw.split())) == len(norm) else None


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _substring_conditions(raw: str, norm: str | None) -> list:
    """The text appears somewhere in the book's fields (tiers 1 and 2).

    With a usable folded query the folded view alone decides: the fold
    drops or maps single characters, so text containing the raw query
    always folds to text containing the folded query — the plain ILIKEs
    could only repeat its hits. It reads Book.search_norm, every folded
    field in one column, so a pattern too short for the trigram index
    costs one LIKE per book rather than seventeen. The ISBN is not
    folded and keeps its plain match.
    """
    if norm is None:
        return book_search_conditions(raw)
    return [
        Book.search_norm.like(f"%{_like_literal(norm)}%"),
        Book.epub_isbn.ilike(f"%{_like_literal(raw)}%"),
    ]


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

    Two settings are made with SET LOCAL — the planning mode below, and
    ``pg_trgm.word_similarity_threshold`` in the fuzzy branch — so the
    caller's real query must run in the same transaction (the normal
    single-session request flow).
    """
    tokens = q.split()[:MAX_QUERY_TOKENS]

    # Plan every search statement for the pattern it actually carries.
    # The driver prepares statements, and after five runs PostgreSQL
    # swaps in a generic plan that cannot know whether the pattern is
    # selective: for the EXISTS probes it walks the whole table testing
    # each row, on the off chance of an early hit, instead of asking
    # the trigram indexes — which settle a miss in under a millisecond.
    await db.execute(text("SET LOCAL plan_cache_mode = force_custom_plan"))

    norm_q = _usable_fold(q, await db.scalar(select(func.beepub_norm(q))))

    # The exact and normalized views are one query semantically — "this
    # text appears in the book's fields" — differing only in formatting,
    # so they are always OR-combined: an exact hit must not mask a
    # differently-formatted sibling (e.g. 「街角VR食堂 早晨篇」 hiding
    # 「街角 VR 食堂 深夜篇」).
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
            or_(*_substring_conditions(token, _usable_fold(token, n)))
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
        return TieredSearch(_no_match(), norm_q, fuzzy=False, mode="phrase")

    if norm_q is None:
        return TieredSearch(_no_match(), norm_q, fuzzy=False, mode="phrase")

    # Trigram extraction only sees alphanumerics (CJK included) — "c++"
    # is a single-letter word to pg_trgm, and one letter word-similarity-
    # matches half the library. Two characters make three trigrams, and
    # reaching the threshold takes two of them — which only text that
    # contains both characters side by side has: a substring hit, and
    # the tier above just ruled that out. Symbols still work in the
    # substring tier.
    if sum(ch.isalnum() for ch in norm_q) < MIN_FUZZY_QUERY_CHARS:
        return TieredSearch(_no_match(), norm_q, fuzzy=False, mode="phrase")

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

    return TieredSearch(_no_match(), norm_q, fuzzy=False, mode="phrase")


def select_exists(scope: Select, conditions: list):
    return select(exists(scope.where(or_(*conditions))))


def relevance_score(search: TieredSearch, q: str):
    """Per-book relevance, lower is better — the "most relevant" sort.

    Exact title first, then a series named exactly this (a search for
    the series itself), then title prefix, then any other hit. The
    normalized views are compared when the query folds to something
    usable, so 「街角 VR 食堂」 still counts as an exact 「街角VR食堂」.
    Any-word searches put books hitting more keywords first: each extra
    keyword outweighs every title tier.
    """
    title_col = func.coalesce(Book.title, Book.epub_title)
    series_col = func.coalesce(Book.series, Book.epub_series)
    if search.normalized_query is not None:
        norm_q = search.normalized_query
        norm_title = normalized_title()
        tier = case(
            (norm_title == norm_q, 0),
            (normalized_series() == norm_q, 1),
            (norm_title.like(f"{norm_q}%"), 2),
            else_=3,
        )
    else:
        tier = case(
            (func.lower(title_col) == q.lower(), 0),
            (func.lower(series_col) == q.lower(), 1),
            (title_col.ilike(f"{q}%"), 2),
            else_=3,
        )
    if search.rank is not None:
        return tier - search.rank * 10
    return tier


def relevance_order(search: TieredSearch, q: str) -> list:
    """ORDER BY clauses for the relevance sort: score, then shorter (and
    then alphabetical) title — among a series' volumes that is volume
    order for the common 「…1」「…2」 naming."""
    title_col = func.coalesce(Book.title, Book.epub_title)
    return [relevance_score(search, q), func.length(title_col), title_col]


def relevance_ranked_ids(matches: Select, search: TieredSearch, q: str) -> Select:
    """The ids of ``matches`` (the caller's query, search conditions
    attached), most relevant first — to page with OFFSET/LIMIT, the
    page's books fetched afterwards.

    A one-character query matches a third of a library, and no index
    gives this order: every match has to be ranked to keep one page.
    Two things keep that cheap. Only the id and the sort keys go through
    the sort, not whole books. And the matches are settled first, behind
    OFFSET 0 — a subquery PostgreSQL will not flatten — so the sort sits
    directly under the LIMIT and keeps a page-sized heap. Flattened, the
    planner sorted every match in full before checking which the user
    may see (measured on 64k books, 21k matches: 350 ms against 105).
    """
    keys = [*relevance_order(search, q), Book.id]
    hits = (
        matches.with_only_columns(*[key.label(f"k{i}") for i, key in enumerate(keys)])
        .offset(0)
        .subquery("hits")
    )
    return select(hits.c[len(keys) - 1]).order_by(*hits.c)
