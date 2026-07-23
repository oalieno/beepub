"""Metadata plugin framework — base types and the plugin contract.

A plugin is one module in this package: a MetadataPlugin subclass that
declares which clues it can locate a book with (`accepts`), which
BookRecord fields it can fill (`provides`), and implements
`resolve(query) -> BookRecord | None`.

This module must not import anything from app.* — plugins receive their
configuration as a plain dict at construction time so every plugin file
stays readable and testable in isolation.
"""

import enum
import re
from abc import ABC
from dataclasses import dataclass, field, fields
from typing import ClassVar

import httpx
from rapidfuzz import fuzz

REQUEST_TIMEOUT = 15

# Fuzzy-match confidence floor for title-located candidates. A search
# engine always returns its closest matches even when the book isn't on
# the site at all — below this score "not found" beats linking the
# wrong book.
MIN_CONFIDENCE = 60

# Store listing decorations (edition markers, bundled extras): not title
# content on either side of a comparison.
_TITLE_DECORATIONS_RE = re.compile(r"【[^】]*】")
_SUBTITLE_SPLIT_RE = re.compile(r"[：:]")
_AUTHOR_NOISE_RE = re.compile(r"[\s·・．.‧,，]+")


def _title_views(title: str) -> tuple[str, str, str | None]:
    """(full, main, subtitle) views of a listing title, lowercased.

    The main/subtitle split is on the first colon; no colon means no
    subtitle view."""
    full = re.sub(r"\s+", " ", _TITLE_DECORATIONS_RE.sub(" ", title)).strip().lower()
    parts = _SUBTITLE_SPLIT_RE.split(full, maxsplit=1)
    main = parts[0].strip()
    subtitle = parts[1].strip() if len(parts) > 1 else ""
    return full, main, subtitle or None


def _authors_disjoint(a: list[str], b: list[str]) -> bool:
    """True only when both sides name authors and none coincide."""
    norm_a = {_AUTHOR_NOISE_RE.sub("", n).casefold() for n in a} - {""}
    norm_b = {_AUTHOR_NOISE_RE.sub("", n).casefold() for n in b} - {""}
    return bool(norm_a) and bool(norm_b) and norm_a.isdisjoint(norm_b)


def title_confidence(
    query_title: str,
    candidate_title: str,
    query_authors: list[str] | None = None,
    candidate_authors: list[str] | None = None,
) -> float:
    """Confidence (0-100) that two listing titles name the same book.

    token_sort_ratio splits on whitespace, so a CJK title compares as a
    single token and a store's rewritten marketing subtitle (「全球熱銷
    突破1000萬冊…」) dilutes a perfect main-title match below
    MIN_CONFIDENCE. When both sides carry a subtitle, also score the
    halves separately and take the weakest link: equal mains plus
    overlapping subtitles is the edition-rewrite pattern, while equal
    mains with unrelated subtitles is a series sibling (哈利波特：…)
    that must stay rejected. Disjoint author sets veto the split view —
    the same main title by someone else is a different book."""
    q_full, q_main, q_subtitle = _title_views(query_title)
    c_full, c_main, c_subtitle = _title_views(candidate_title)

    score = fuzz.token_sort_ratio(q_full, c_full)
    if (
        q_main
        and c_main
        and q_subtitle
        and c_subtitle
        and not _authors_disjoint(query_authors or [], candidate_authors or [])
    ):
        split_score = min(
            fuzz.ratio(q_main, c_main),
            fuzz.partial_ratio(q_subtitle, c_subtitle),
        )
        score = max(score, split_score)
    return score


class Clue(enum.StrEnum):
    ISBN = "isbn"
    TITLE = "title"
    URL = "url"


class RateLimitError(Exception):
    def __init__(self, source: str):
        super().__init__(f"{source} rate limited (429)")
        self.source = source


@dataclass
class BookQuery:
    """Locating clues. All optional — callers pass everything they have.

    When `url` is set it is a value this same plugin produced earlier
    (its stored source_url) or that an admin entered for it, so plugins
    may interpret it liberally (bare IDs, slugs, full URLs)."""

    title: str | None = None
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    url: str | None = None


@dataclass
class BookRecord:
    """A plugin's complete output for one located book.

    Values are raw, as the source states them — normalization (tag
    vocabulary mapping, date/language canonicalization) happens
    centrally, never in plugins. Partial records are fine."""

    source_url: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    description: str | None = None
    published_date: str | None = None
    language: str | None = None
    cover_url: str | None = None
    tags: list[str] = field(default_factory=list)
    rating: float | None = None
    rating_count: int | None = None
    readers_count: int | None = None  # e.g. hardcover's users_read_count
    reviews: list[dict] | None = None


# Field names a plugin may list in `provides` (source_url is universal
# bookkeeping, not a data capability). The ordered tuple drives stable
# display ordering.
RECORD_FIELD_ORDER = tuple(f.name for f in fields(BookRecord) if f.name != "source_url")
RECORD_FIELDS = frozenset(RECORD_FIELD_ORDER)


@dataclass
class SearchCandidate:
    """One hit from a plugin's internal search, consumed by the default
    resolve(). `exact` marks ISBN-located hits (skips fuzzy scoring);
    `prefetched` carries a full record when the search response already
    contained everything (skips the _fetch round-trip).

    publisher/published_date/cover_url are display garnish for the
    two-step candidate list — fill them when the search response has
    them for free, never with extra requests."""

    url: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    exact: bool = False
    prefetched: BookRecord | None = None
    publisher: str | None = None
    published_date: str | None = None
    cover_url: str | None = None


class MetadataPlugin(ABC):
    """The contract is resolve(query) -> BookRecord | None; everything
    else is convenience. Plugins that fit the common "search, pick the
    best hit, parse its book page" shape implement _search()/_fetch()
    and inherit the default resolve(); any other crawl shape overrides
    resolve() directly and does whatever it needs inside."""

    name: ClassVar[str]
    label: ClassVar[str]
    kind: ClassVar[str] = "scraper"  # "api" | "scraper" — display only
    locale: ClassVar[str | None] = None  # e.g. "zh-TW" — display only
    accepts: ClassVar[frozenset[Clue]] = frozenset()
    provides: ClassVar[frozenset[str]] = frozenset()  # BookRecord field names
    cover_hosts: ClassVar[frozenset[str]] = frozenset()
    settings_keys: ClassVar[tuple[str, ...]] = ()
    secret_settings_keys: ClassVar[tuple[str, ...]] = ()
    key_url: ClassVar[str | None] = None  # where the operator gets a key
    ratelimit_cooldown: ClassVar[int] = 300  # seconds; enforced by the job runner
    # Manual-linking metadata; all three set <=> Clue.URL in accepts.
    url_prefix: ClassVar[str | None] = None
    id_pattern: ClassVar[str | None] = None
    id_hint: ClassVar[str | None] = None

    def __init__(self, settings: dict[str, str] | None = None):
        self.settings = settings or {}

    def _client(self, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        """Shared HTTP client: timeout, redirects, 429 -> RateLimitError.
        Plugins never implement rate limiting, retries, or sleeps."""
        source = self.name

        async def _raise_on_429(response: httpx.Response) -> None:
            if response.status_code == 429:
                raise RateLimitError(source)

        return httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers=headers or {},
            event_hooks={"response": [_raise_on_429]},
        )

    async def candidates(self, query: BookQuery) -> list[SearchCandidate]:
        """Raw search hits for the interactive two-step flow: the user
        sees this plugin's candidates and picks one; the picked
        candidate's `url` comes back later as the `url` clue of a
        resolve(). Judgment (fuzzy scoring, confidence floors) stays out
        — the whole point is showing the user what resolve() would have
        judged. Default lifts _search(); single-shot plugins without one
        have no candidates to offer."""
        try:
            return await self._search(query)
        except NotImplementedError:
            return []

    async def resolve(self, query: BookQuery) -> BookRecord | None:
        if query.url and Clue.URL in self.accepts:
            return await self._fetch(query.url)

        best: SearchCandidate | None = None
        best_score = -1.0
        for candidate in await self._search(query):
            if candidate.exact:
                best, best_score = candidate, 100.0
                break
            if not query.title:
                continue
            score = title_confidence(
                query.title, candidate.title, query.authors, candidate.authors
            )
            if score > best_score:
                best, best_score = candidate, score

        if best is None or best_score < MIN_CONFIDENCE:
            return None
        if best.prefetched is not None:
            return best.prefetched
        return await self._fetch(best.url)

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        raise NotImplementedError

    async def _fetch(self, url: str) -> BookRecord:
        raise NotImplementedError
