"""books.com.tw (博客來) plugin — TW-edition bibliographic data and covers.

One request to the ISBN search page (which answers plain requests given
a browser UA) yields the title (result-item anchor), authors/publisher
(the advanced-filter facets), and the cover via the open im1 image
proxy — full size when the w/h params are omitted. The product page
403s scripted fetches, so publication date and description are out of
reach: records are partial, and if even the title can't be parsed the
plugin degrades to a cover-only record."""

import logging
import re

from bs4 import BeautifulSoup

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
)

logger = logging.getLogger(__name__)

SEARCH_URL = "https://search.books.com.tw/search/query/key/{isbn}"

# The plain www.books.com.tw image path 403s scripted fetches; the im1
# proxy serves it openly, full-size when w/h are omitted.
_IMG_RE = re.compile(
    r"https://im\d\.book\.com\.tw/image/getImage\?i="
    r"(https://www\.books\.com\.tw/img/[^&\"\s]+\.jpg)"
)
_ITEM_ID_RE = re.compile(r"/item/(\d+)/")
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
    accepts = frozenset({Clue.ISBN})
    provides = frozenset({"title", "authors", "publisher", "cover_url"})
    cover_hosts = frozenset({"im1.book.com.tw", "im2.book.com.tw"})

    async def resolve(self, query: BookQuery) -> BookRecord | None:
        if not query.isbn:
            return None
        try:
            async with self._client(HEADERS) as client:
                resp = await client.get(SEARCH_URL.format(isbn=query.isbn))
                if resp.status_code != 200:
                    return None
                html = resp.text
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"books.com.tw search failed: {e}")
            return None
        return self._parse_search_page(html)

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
                source_url = f"https://www.books.com.tw/products/{item_match.group(1)}"

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
