"""ISBN → display metadata for the add-physical-book prefill.

Google Books first (best data, but keyless access 429s aggressively —
effectively requires the operator's google_books_api_key), then Open
Library as the keyless fallback."""

import logging

import httpx

from app.services.metadata_sources.base import REQUEST_TIMEOUT, RateLimitError
from app.services.metadata_sources.google_books import (
    lookup_isbn as google_lookup_isbn,
)

logger = logging.getLogger(__name__)

OPENLIBRARY_SEARCH = "https://openlibrary.org/search.json"


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
    try:
        info = await google_lookup_isbn(isbn, api_key=google_api_key)
        if info:
            return info
    except RateLimitError:
        pass  # fall through to Open Library
    return await _openlibrary_lookup(isbn)
