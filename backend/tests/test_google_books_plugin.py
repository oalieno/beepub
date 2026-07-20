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


def test_url_pick_with_title_rebuilds_the_search_stash(monkeypatch):
    """A candidate pick (or a pinned URL in the job) arrives on a fresh
    instance. With the original clues riding along, resolve re-runs the
    search so the merge keeps the search-only TW description."""
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(
        GoogleBooksPlugin().resolve(BookQuery(url="o5zjzwEACAAJ", title="神"))
    )

    assert record is not None
    assert record.description == "search-only description for a TW no-preview volume"
    assert record.publisher == "聯經出版事業公司"  # search-first again
    assert record.cover_url == "https://books.google.com/thumb?id=x"


def test_reflow_restores_cjk_line_breaks_google_flattened():
    """Google flattens description line breaks into ASCII spaces; between
    two CJK characters such a space can only be that scar."""
    from app.plugins.metadata.google_books import _reflow_description

    flat = (
        "人生有限而且短暫， 到底要把握當下？ ＃規則訂明＃ PChome Online網路家庭 詹宏志"
    )
    assert _reflow_description(flat) == (
        "人生有限而且短暫，\n到底要把握當下？\n＃規則訂明＃ PChome Online網路家庭\n詹宏志"
    )
    # Latin prose is indistinguishable from normal spacing — untouched.
    english = "A tale of two cities. It was the best of times."
    assert _reflow_description(english) == english
    # Anything already carrying newlines was not flattened — untouched.
    formatted = "第一行\n第二行 保留"
    assert _reflow_description(formatted) == formatted
    assert _reflow_description(None) is None
