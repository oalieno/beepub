"""books.com.tw plugin parser tests against a trimmed real search page."""

import asyncio
from pathlib import Path

import httpx

from app.plugins.metadata.base import BookQuery
from app.plugins.metadata.books_tw import BooksTwPlugin

FIXTURE = Path(__file__).parent / "fixtures" / "books_tw_search.html"


def test_parse_search_page_extracts_partial_record():
    record = BooksTwPlugin._parse_search_page(FIXTURE.read_text(encoding="utf-8"))

    assert record is not None
    assert record.title == "神(董啟章長篇小說《心》姊妹篇)"
    assert record.authors == ["董啟章"]
    assert record.publisher == "聯經出版公司"
    assert record.source_url == "https://www.books.com.tw/products/0010752879"
    assert record.cover_url == (
        "https://im1.book.com.tw/image/getImage"
        "?i=https://www.books.com.tw/img/001/075/28/0010752879.jpg"
    )
    # The product page is unreachable for scripts — these stay unset.
    assert record.description is None
    assert record.published_date is None


def test_parse_degrades_to_cover_only_when_title_missing():
    html = """
    <html><body>
      <img data-src="https://im1.book.com.tw/image/getImage?i=https://www.books.com.tw/img/001/075/28/0010752879.jpg&amp;w=187&amp;h=187">
    </body></html>
    """
    record = BooksTwPlugin._parse_search_page(html)

    assert record is not None
    assert record.title is None
    assert record.cover_url and "getImage" in record.cover_url


def test_parse_returns_none_when_nothing_found():
    assert BooksTwPlugin._parse_search_page("<html><body></body></html>") is None


def test_resolve_requires_isbn():
    assert asyncio.run(BooksTwPlugin().resolve(BookQuery(title="神"))) is None


def test_resolve_fetches_search_page(monkeypatch):
    fixture_html = FIXTURE.read_text(encoding="utf-8")
    requested: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, params: dict | None = None):
            requested.append(url)
            return httpx.Response(
                200, text=fixture_html, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(BooksTwPlugin().resolve(BookQuery(isbn="9789570849523")))

    assert requested == ["https://search.books.com.tw/search/query/key/9789570849523"]
    assert record is not None
    assert record.title == "神(董啟章長篇小說《心》姊妹篇)"
