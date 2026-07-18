"""Google Books plugin: the search/detail merge.

The two endpoints omit fields in BOTH directions — search hits often
lack imageLinks (cover regression, fixed by reading the detail), while
the detail record drops description for TW no-preview volumes
(description regression, fixed by merging search-first). This guards
both directions at once."""

import asyncio
import json

import httpx

from app.plugins.metadata.base import BookQuery
from app.plugins.metadata.google_books import GoogleBooksPlugin

SEARCH_PAYLOAD = {
    "items": [
        {
            "id": "o5zjzwEACAAJ",
            "volumeInfo": {
                "title": "神",
                "authors": ["董啟章"],
                "publisher": "聯經出版事業公司",
                "description": "search-only description for a TW no-preview volume",
                # no imageLinks — the search endpoint routinely omits them
            },
        }
    ]
}

DETAIL_PAYLOAD = {
    "volumeInfo": {
        "title": "神",
        "authors": ["董啟章"],
        "publisher": "聯經",
        # no description — the detail drops it for this volume
        "publishedDate": "2017",
        "language": "zh",
        "imageLinks": {"thumbnail": "http://books.google.com/thumb?id=x&edge=curl"},
    }
}


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, params: dict | None = None):
        payload = DETAIL_PAYLOAD if "/volumes/" in url else SEARCH_PAYLOAD
        return httpx.Response(
            200,
            text=json.dumps(payload),
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", url, params=params),
        )


def test_resolve_merges_search_description_with_detail_cover(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(GoogleBooksPlugin().resolve(BookQuery(isbn="9789570849523")))

    assert record is not None
    # From the search response (detail lacks it):
    assert record.description == "search-only description for a TW no-preview volume"
    # Search-first for scalars present on both sides:
    assert record.publisher == "聯經出版事業公司"
    # Backfilled from the detail (search lacks them):
    assert record.published_date == "2017"
    assert record.language == "zh"
    # Cover comes from the detail, https-upgraded, edge=curl stripped:
    assert record.cover_url == "https://books.google.com/thumb?id=x"


def test_pinned_fetch_without_prior_search_still_works(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(
        GoogleBooksPlugin().resolve(
            BookQuery(url="https://books.google.com/books?id=o5zjzwEACAAJ")
        )
    )

    assert record is not None
    assert record.source_url == "o5zjzwEACAAJ"
    assert record.publisher == "聯經"  # detail only — no search stash
    assert record.cover_url == "https://books.google.com/thumb?id=x"
