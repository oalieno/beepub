"""ISBN → display metadata for the add-physical-book prefill.

Google Books first (best data, but keyless access 429s aggressively —
effectively requires the operator's google_books_api_key), then Open
Library as the keyless fallback. Covers get their own fallback chain:
Taiwanese ISBNs are usually metadata-only records upstream (no
imageLinks on Google, no cover_i on OL), while books.com.tw carries
nearly every TW edition."""

import logging
import re

import httpx

from app.services.metadata_sources.base import REQUEST_TIMEOUT, RateLimitError
from app.services.metadata_sources.google_books import (
    lookup_isbn as google_lookup_isbn,
)

logger = logging.getLogger(__name__)

OPENLIBRARY_SEARCH = "https://openlibrary.org/search.json"

BOOKS_TW_SEARCH = "https://search.books.com.tw/search/query/key/{isbn}"
# The plain www.books.com.tw image path 403s scripted fetches; the im1
# image proxy serves it openly, full-size when w/h are omitted.
_BOOKS_TW_IMG_RE = re.compile(
    r"https://im\d\.book\.com\.tw/image/getImage\?i="
    r"(https://www\.books\.com\.tw/img/[^&\"\s]+\.jpg)"
)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}


async def _books_tw_cover(isbn: str) -> str | None:
    """Cover-only fallback from the books.com.tw ISBN search."""
    try:
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(BOOKS_TW_SEARCH.format(isbn=isbn))
            if resp.status_code != 200:
                return None
            match = _BOOKS_TW_IMG_RE.search(resp.text)
            if not match:
                return None
            return f"https://im1.book.com.tw/image/getImage?i={match.group(1)}"
    except Exception as e:
        logger.warning(f"books.com.tw cover lookup failed: {e}")
        return None


async def _openlibrary_lookup(isbn: str) -> dict | None:
    params = {
        "isbn": isbn,
        "fields": "title,author_name,publisher,first_publish_year,cover_i",
        "limit": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(OPENLIBRARY_SEARCH, params=params)
            if resp.status_code != 200:
                return None
            docs = resp.json().get("docs") or []
            if not docs:
                return None
            doc = docs[0]
            cover_id = doc.get("cover_i")
            publishers = doc.get("publisher") or []
            year = doc.get("first_publish_year")
            return {
                "title": doc.get("title"),
                "authors": doc.get("author_name", []),
                "publisher": publishers[0] if publishers else None,
                "description": None,
                "published_date": str(year) if year else None,
                # Open Library language codes are MARC (eng/jpn); leave the
                # field to the user rather than guessing a mapping.
                "language": None,
                "cover_url": (
                    f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
                    if cover_id
                    else None
                ),
            }
    except Exception as e:
        logger.warning(f"Open Library ISBN lookup failed: {e}")
        return None


async def lookup_isbn(isbn: str, google_api_key: str = "") -> dict | None:
    info = None
    try:
        info = await google_lookup_isbn(isbn, api_key=google_api_key)
    except RateLimitError:
        pass  # fall through to Open Library
    if not info:
        info = await _openlibrary_lookup(isbn)
    if info and not info.get("cover_url"):
        # Metadata found but no cover art upstream — the common case for
        # TW editions. books.com.tw first, then the Open Library by-ISBN
        # guess (default=false 404s cleanly; the UI drops broken previews).
        info["cover_url"] = (
            await _books_tw_cover(isbn)
            or f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
        )
    return info
