"""ISBN → display metadata for the add-physical-book prefill.

A thin chain over the metadata plugins (Google Books → Open Library,
then the books.com.tw / Open Library cover fallbacks), preserving the
single-result endpoint contract. The per-source fan-out with provenance
replaces this in the next step."""

import logging

from app.plugins.metadata import BookQuery, BookRecord, RateLimitError
from app.plugins.metadata.books_tw import BooksTwPlugin
from app.plugins.metadata.google_books import GoogleBooksPlugin
from app.plugins.metadata.open_library import OpenLibraryPlugin

logger = logging.getLogger(__name__)


def _as_dict(record: BookRecord) -> dict:
    return {
        "title": record.title,
        "authors": record.authors,
        "publisher": record.publisher,
        "description": record.description,
        "published_date": record.published_date,
        "language": record.language,
        "cover_url": record.cover_url,
    }


async def lookup_isbn(isbn: str, google_api_key: str = "") -> dict | None:
    query = BookQuery(isbn=isbn)

    record: BookRecord | None = None
    try:
        record = await GoogleBooksPlugin(
            {"google_books_api_key": google_api_key}
        ).resolve(query)
    except RateLimitError:
        pass  # fall through to Open Library

    if record is None or record.title is None:
        try:
            ol = await OpenLibraryPlugin().resolve(query)
        except RateLimitError:
            ol = None
        if ol is not None and ol.title is not None:
            record = ol

    if record is None or record.title is None:
        return None

    info = _as_dict(record)
    if not info.get("cover_url"):
        # Metadata found but no cover art upstream — the common case for
        # TW editions. books.com.tw first, then the Open Library by-ISBN
        # guess (default=false 404s cleanly; the UI drops broken previews).
        try:
            tw = await BooksTwPlugin().resolve(query)
        except RateLimitError:
            tw = None
        info["cover_url"] = (tw.cover_url if tw else None) or (
            f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
        )
    return info
