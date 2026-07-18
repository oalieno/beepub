"""Open Library plugin — keyless bibliographic lookup and covers by ISBN."""

import logging

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
)

logger = logging.getLogger(__name__)

SEARCH_URL = "https://openlibrary.org/search.json"


class OpenLibraryPlugin(MetadataPlugin):
    name = "open_library"
    label = "Open Library"
    kind = "api"
    accepts = frozenset({Clue.ISBN})
    provides = frozenset(
        {"title", "authors", "publisher", "published_date", "cover_url"}
    )
    cover_hosts = frozenset({"covers.openlibrary.org"})

    async def resolve(self, query: BookQuery) -> BookRecord | None:
        if not query.isbn:
            return None

        # The by-ISBN guess costs no request and 404s cleanly
        # (default=false) — consumers drop broken previews.
        cover_guess = (
            f"https://covers.openlibrary.org/b/isbn/{query.isbn}-L.jpg?default=false"
        )

        params = {
            "isbn": query.isbn,
            "fields": "title,author_name,publisher,first_publish_year,cover_i",
            "limit": 1,
        }
        try:
            async with self._client() as client:
                resp = await client.get(SEARCH_URL, params=params)
                if resp.status_code != 200:
                    return BookRecord(cover_url=cover_guess)
                docs = resp.json().get("docs") or []
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Open Library ISBN lookup failed: {e}")
            return None

        if not docs:
            # No bibliographic record — the cover guess alone is still a
            # worthwhile candidate.
            return BookRecord(cover_url=cover_guess)

        doc = docs[0]
        cover_id = doc.get("cover_i")
        publishers = doc.get("publisher") or []
        year = doc.get("first_publish_year")
        return BookRecord(
            title=doc.get("title"),
            authors=doc.get("author_name") or [],
            publisher=publishers[0] if publishers else None,
            published_date=str(year) if year else None,
            # Open Library language codes are MARC (eng/jpn) — left unset
            # rather than guessing a mapping.
            cover_url=(
                f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
                if cover_id
                else cover_guess
            ),
        )
