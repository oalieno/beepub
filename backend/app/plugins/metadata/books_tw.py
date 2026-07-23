"""books.com.tw (博客來) plugin — TW-edition bibliographic data and covers.

The search page answers plain requests given a browser UA, for ISBN and
title queries alike; the product page 403s scripted fetches, so records
are built entirely from search result data and stay partial (no
description or date). An ISBN query lands a single exact hit whose page
facets add authors/publisher; title queries parse per-result items
(div.table-td) into candidates. Because the product page is
unreachable, a candidate pick or pinned URL re-runs the search with the
other clues and lands on the item whose product id matches — an id the
search can't find again answers a bare record, never a guess."""

import logging
import re

from bs4 import BeautifulSoup

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
    SearchCandidate,
)

logger = logging.getLogger(__name__)

PRODUCT_URL = "https://www.books.com.tw/products/{item_id}"
SEARCH_URL = "https://search.books.com.tw/search/query/key/{query}"

# The plain www.books.com.tw image path 403s scripted fetches; the im1
# proxy serves it openly, full-size when w/h are omitted.
_IMG_RE = re.compile(
    r"https://im\d\.book\.com\.tw/image/getImage\?i="
    r"(https://www\.books\.com\.tw/img/[^&\"\s]+\.jpg)"
)
_ITEM_ID_RE = re.compile(r"/item/(\d+)/")
_PRODUCT_ID_RE = re.compile(r"(\d+)/?$")
_FACET_COUNT_RE = re.compile(r"\(\d+\)\s*$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}


class BooksTwPlugin(MetadataPlugin):
    name = "books_tw"
    label = "博客來"
    kind = "scraper"
    locale = "zh-TW"
    accepts = frozenset({Clue.ISBN, Clue.TITLE, Clue.URL})
    provides = frozenset({"title", "authors", "publisher", "cover_url"})
    cover_hosts = frozenset({"im1.book.com.tw", "im2.book.com.tw"})
    url_prefix = "https://www.books.com.tw/products/"
    id_pattern = r"^\d+$"
    id_hint = "e.g. 0010752879"

    async def _get_search_page(self, query: str) -> str | None:
        """One search request; an unknown ISBN answers 404 (verified
        live), which reads as not-found, not an error."""
        try:
            async with self._client(HEADERS) as client:
                resp = await client.get(SEARCH_URL.format(query=query))
                if resp.status_code != 200:
                    return None
                return resp.text
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"books.com.tw search failed: {e}")
            return None

    @staticmethod
    def _build_queries(title: str) -> list[str]:
        normalized = re.sub(r"[（(][^）)]*[）)]", "", title)
        normalized = re.sub(r"[【\[][^】\]]*[】\]]", "", normalized)
        normalized = " ".join(normalized.split()).strip()
        queries = [title.strip()]
        if normalized and normalized not in queries:
            queries.append(normalized)
        return queries

    @staticmethod
    def _cover_from_img(img) -> str | None:
        if img is None:
            return None
        src = img.get("data-src") or img.get("src") or ""
        match = _IMG_RE.search(src)
        if match:
            return f"https://im1.book.com.tw/image/getImage?i={match.group(1)}"
        return None

    @classmethod
    def _parse_search_items(cls, html: str, limit: int) -> list[SearchCandidate]:
        """Per-result items of a title search. Publisher only exists in
        the page-level facets (aggregated across hits), so item records
        go without it."""
        soup = BeautifulSoup(html, "lxml")
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        for td in soup.select("div.table-td"):
            anchor = td.select_one('h4 a[href*="area/mid_name"]')
            if anchor is None:
                continue
            id_match = _ITEM_ID_RE.search(anchor.get("href", ""))
            if id_match is None:
                continue
            url = PRODUCT_URL.format(item_id=id_match.group(1))
            if url in seen:
                continue
            title = (anchor.get("title") or anchor.get_text(strip=True) or "").strip()
            if not title:
                continue
            authors = [
                a.get_text(strip=True)
                for a in td.select('p.author a[rel="go_author"]')
                if a.get_text(strip=True)
            ]
            cover = cls._cover_from_img(td.select_one("img"))
            seen.add(url)
            candidates.append(
                SearchCandidate(
                    url=url,
                    title=title,
                    authors=authors,
                    cover_url=cover,
                    prefetched=BookRecord(
                        source_url=url, title=title, authors=authors, cover_url=cover
                    ),
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        """Title search only — the ISBN path stays in resolve() because
        its single-hit page parse (facet authors/publisher, cover-only
        degradation) doesn't map onto candidates."""
        if not query.title:
            return []
        for q in self._build_queries(query.title):
            html = await self._get_search_page(q)
            if html is None:
                continue
            candidates = self._parse_search_items(html, limit=5)
            if candidates:
                return candidates
        return []

    async def resolve(self, query: BookQuery) -> BookRecord | None:
        if query.url:
            return await self._resolve_pick(query)
        if query.isbn:
            html = await self._get_search_page(query.isbn)
            if html is not None:
                record = self._parse_search_page(html)
                if record is not None:
                    return record
        if query.title:
            # Base scoring over the title candidates; records ride in
            # prefetched so no product-page fetch is ever attempted.
            return await super().resolve(
                BookQuery(title=query.title, authors=query.authors)
            )
        return None

    async def _resolve_pick(self, query: BookQuery) -> BookRecord:
        """The product page can't be fetched, so a pick/pinned URL
        re-runs the search with the remaining clues and matches the
        product id."""
        id_match = _PRODUCT_ID_RE.search(query.url or "")
        canonical = (
            PRODUCT_URL.format(item_id=id_match.group(1))
            if id_match
            else (query.url or "")
        )
        if query.isbn:
            html = await self._get_search_page(query.isbn)
            if html is not None:
                record = self._parse_search_page(html)
                if record is not None and record.source_url == canonical:
                    return record
        if query.title:
            for candidate in await self._search(query):
                if candidate.url == canonical and candidate.prefetched is not None:
                    return candidate.prefetched
        return BookRecord(source_url=canonical)

    @staticmethod
    def _facet_values(soup: BeautifulSoup, form_id: str) -> list[str]:
        """Facet labels read like 「董啟章(1)」 — strip the hit count."""
        values: list[str] = []
        for label in soup.select(f"#{form_id} label"):
            text = _FACET_COUNT_RE.sub("", label.get_text(strip=True)).strip()
            if text and text not in values:
                values.append(text)
        return values

    @classmethod
    def _parse_search_page(cls, html: str) -> BookRecord | None:
        """Single-hit (ISBN) page: first result anchor plus the page
        facets, which aggregate to exactly this book's authors and
        publisher when the ISBN matched one edition."""
        cover_url = None
        img_match = _IMG_RE.search(html)
        if img_match:
            cover_url = f"https://im1.book.com.tw/image/getImage?i={img_match.group(1)}"

        soup = BeautifulSoup(html, "lxml")

        title = None
        source_url = None
        title_anchor = soup.select_one(
            'a[href*="/redirect/move/"][href*="area/mid_name"]'
        )
        if title_anchor:
            title = title_anchor.get("title") or title_anchor.get_text(strip=True)
            item_match = _ITEM_ID_RE.search(title_anchor.get("href", ""))
            if item_match:
                source_url = PRODUCT_URL.format(item_id=item_match.group(1))

        if not title:
            # Structure drift or no hit — a cover alone is still useful.
            return BookRecord(cover_url=cover_url) if cover_url else None

        return BookRecord(
            source_url=source_url,
            title=title,
            authors=cls._facet_values(soup, "adv_author_origin"),
            publisher=next(
                iter(cls._facet_values(soup, "adv_publishing_origin")), None
            ),
            cover_url=cover_url,
        )
