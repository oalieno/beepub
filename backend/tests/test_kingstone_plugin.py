"""Kingstone plugin parser tests against trimmed real pages.

The search fixture keeps the header's trending-keyword /basic/ links on
purpose: the parser must stay inside li.displayunit result items — the
header links point at unrelated books (that exact page-wide scan once
fetched a stranger during development)."""

import asyncio
from pathlib import Path

import httpx

from app.plugins.metadata.base import BookQuery
from app.plugins.metadata.kingstone import KingstonePlugin

SEARCH_FIXTURE = Path(__file__).parent / "fixtures" / "kingstone_search.html"
PRODUCT_FIXTURE = Path(__file__).parent / "fixtures" / "kingstone_product.html"


def test_search_items_scoped_to_result_units():
    candidates = KingstonePlugin._parse_search_items(
        SEARCH_FIXTURE.read_text(encoding="utf-8"), limit=5
    )

    # 2 result units in the fixture; the 3 header keyword links must not
    # leak in.
    assert [c.title for c in candidates] == [
        "世界上最透明的故事2",
        "世界上最透明的故事【1+2套書】",
    ]
    first = candidates[0]
    assert first.url == "https://www.kingstone.com.tw/basic/2018612590237/"
    assert first.authors == ["杉井光"]
    assert first.publisher == "皇冠文化"
    assert first.cover_url and first.cover_url.startswith(
        "https://cdn.kingstone.com.tw/"
    )


def test_product_page_parses_ld_dom_and_intro():
    record = KingstonePlugin._parse_product_page(
        PRODUCT_FIXTURE.read_text(encoding="utf-8"),
        "https://www.kingstone.com.tw/basic/2015790031699/",
    )

    assert record.title == "唯紅花綻放：習近平時代的認同與歸屬"
    assert record.authors == ["馮哲芸"]
    assert record.publisher == "衛城出版"
    assert record.published_date == "2026/04/01"
    assert record.cover_url and record.cover_url.startswith(
        "https://cdn.kingstone.com.tw/"
    )
    assert record.rating == 4.0
    assert record.rating_count == 1
    # BreadcrumbList minus 首頁.
    assert record.tags == ["中文書", "社會哲思", "社會議題", "社會觀察評論"]
    # Full 內容簡介 panel, heading stripped.
    assert record.description is not None
    assert record.description.startswith("一部獻給中國多元性的輓歌")
    assert "內容簡介" not in record.description


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, **kwargs):
        if "/basic/" in url:
            text = PRODUCT_FIXTURE.read_text(encoding="utf-8")
        elif "9789999999999" in url:
            text = "<html><body><div class='search_result_page'></div></body></html>"
        else:
            text = SEARCH_FIXTURE.read_text(encoding="utf-8")
        return httpx.Response(
            200,
            text=text,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )


def test_resolve_isbn_hit_fetches_the_product_page(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(KingstonePlugin().resolve(BookQuery(isbn="9786267835241")))

    assert record is not None
    assert record.title == "唯紅花綻放：習近平時代的認同與歸屬"
    assert record.published_date == "2026/04/01"


def test_isbn_resolve_prefers_print_over_ebook_listing(monkeypatch):
    """A print ISBN also matches its linked ebook listing, which
    kingstone can rank first — resolve must land on the print page."""
    search_html = """
    <html><body><ul class="displaycol">
      <li class="displayunit">
        <h3 class="pdnamebox"><a href="/basic/111/">【電子書】某書</a></h3>
      </li>
      <li class="displayunit">
        <h3 class="pdnamebox"><a href="/basic/222/">某書</a></h3>
      </li>
    </ul></body></html>
    """
    requested: list[str] = []

    class EbookFirstClient(FakeAsyncClient):
        async def get(self, url: str, **kwargs):
            requested.append(url)
            if "/basic/" in url:
                return await super().get(url, **kwargs)
            return httpx.Response(
                200,
                text=search_html,
                headers={"content-type": "text/html"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", EbookFirstClient)

    record = asyncio.run(KingstonePlugin().resolve(BookQuery(isbn="9786267835241")))

    assert record is not None
    assert requested[-1] == "https://www.kingstone.com.tw/basic/222/"


def test_resolve_unknown_isbn_returns_none(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    assert (
        asyncio.run(KingstonePlugin().resolve(BookQuery(isbn="9789999999999"))) is None
    )


def test_pick_fetches_by_bare_product_id(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(KingstonePlugin().resolve(BookQuery(url="2015790031699")))

    assert record is not None
    assert record.title == "唯紅花綻放：習近平時代的認同與歸屬"
    assert record.source_url == "https://www.kingstone.com.tw/basic/2015790031699/"
