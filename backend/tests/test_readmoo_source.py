import asyncio

import httpx
from bs4 import BeautifulSoup

from app.plugins.metadata.base import BookQuery
from app.plugins.metadata.readmoo import ReadmooPlugin


class FakeAsyncClient:
    requests: list[tuple[str, str]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, params: dict | None = None):
        query = (params or {}).get("q", "")
        self.__class__.requests.append((url, query))

        if query == "9789570849523":
            html = """
            <html><body>
              <h4><a class='product-link' href='/book/210071675000101'>神</a></h4>
            </body></html>
            """
        elif query == "極限返航（電影書衣典藏版） 安迪．威爾（Andy Weir）":
            html = "<html><body><div>No results</div></body></html>"
        elif query == "極限返航（電影書衣典藏版）":
            html = "<html><body><div>No results</div></body></html>"
        elif query == "極限返航 安迪．威爾（Andy Weir）":
            html = """
            <html><body>
              <div class='book-info'>
                <a href='/book/210290289000101'>
                  <span class='book-title'>極限返航</span>
                </a>
              </div>
            </body></html>
            """
        else:
            html = "<html><body></body></html>"

        return httpx.Response(
            200, text=html, request=httpx.Request("GET", url, params=params)
        )


class FakeFetchClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, params: dict | None = None):
        html = """
        <html><body>
          <h1 class='book-detail-title'>神</h1>
          <a href='/contributor/x'><span itemprop='author'>董啟章</span></a>
          <div class='quick-btn-star'>
            <div itemprop='ratingValue' content='4.7'></div>
            共 <span itemprop='ratingCount'>237</span> 人評分
          </div>
          <div class='my-3 border-bottom' itemprop='text' id='book-detail-description'>
            <h2><i class='mo mo-bookinfo'></i> 詳細資訊</h2>
            <p>香港知名作家董啟章出道以來，尺度最大<br/><br/>《心》姊妹篇，長篇情慾小說</p>
          </div>
        </body></html>
        """
        return httpx.Response(
            200, text=html, request=httpx.Request("GET", url, params=params)
        )


def test_build_queries_normalizes_and_deduplicates():
    queries = ReadmooPlugin._build_queries(
        "極限返航（電影書衣典藏版）", ["安迪．威爾（Andy Weir）"]
    )

    assert queries == [
        "極限返航（電影書衣典藏版） 安迪．威爾（Andy Weir）",
        "極限返航（電影書衣典藏版）",
        "極限返航 安迪．威爾（Andy Weir）",
        "極限返航",
    ]


def test_build_queries_strips_square_bracket_subtitle():
    queries = ReadmooPlugin._build_queries("千年鬼【直木獎得主西條奈加最催淚之作】", [])

    assert queries == [
        "千年鬼【直木獎得主西條奈加最催淚之作】",
        "千年鬼",
    ]


def test_extract_book_links_filters_non_book_links_and_dedups():
    html = """
    <html><body>
      <a href='https://readmoo.com/leaderboard/book/instant'>綜合榜</a>
      <h4><a class='product-link' href='https://readmoo.com/book/210217152000101'>極限返航</a></h4>
      <a class='product-link' href='/book/210217152000101'>極限返航</a>
      <h4>
        <a class='product-link' href='/book/210451960000101'>
          極限返航（電影書封典藏版）
        </a>
      </h4>
    </body></html>
    """

    soup = BeautifulSoup(html, "html.parser")
    links = ReadmooPlugin._extract_book_links(soup, limit=5)

    assert links == [
        ("https://readmoo.com/book/210217152000101", "極限返航"),
        ("https://readmoo.com/book/210451960000101", "極限返航（電影書封典藏版）"),
    ]


def test_search_falls_back_to_normalized_query(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    plugin = ReadmooPlugin()
    candidates = asyncio.run(
        plugin._search(
            BookQuery(
                title="極限返航（電影書衣典藏版）", authors=["安迪．威爾（Andy Weir）"]
            )
        )
    )

    assert len(candidates) == 1
    assert candidates[0].title == "極限返航"
    assert candidates[0].url == "https://readmoo.com/book/210290289000101"
    assert FakeAsyncClient.requests == [
        (
            "https://readmoo.com/search/keyword",
            "極限返航（電影書衣典藏版） 安迪．威爾（Andy Weir）",
        ),
        ("https://readmoo.com/search/keyword", "極限返航（電影書衣典藏版）"),
        ("https://readmoo.com/search/keyword", "極限返航 安迪．威爾（Andy Weir）"),
    ]


def test_isbn_search_is_exact_and_skips_title_queries(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    plugin = ReadmooPlugin()
    candidates = asyncio.run(
        plugin._search(BookQuery(title="神", isbn="9789570849523"))
    )

    assert len(candidates) == 1
    assert candidates[0].exact
    assert candidates[0].url == "https://readmoo.com/book/210071675000101"
    # ISBN hit means no title-query fallback requests.
    assert FakeAsyncClient.requests == [
        ("https://readmoo.com/search/keyword", "9789570849523"),
    ]


def test_fetch_parses_bibliographic_fields_and_rating(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeFetchClient)

    plugin = ReadmooPlugin()
    record = asyncio.run(plugin._fetch("https://readmoo.com/book/210363642000101"))

    assert record.rating == 4.7
    assert record.rating_count == 237
    assert record.title == "神"
    assert record.authors == ["董啟章"]
    # The 詳細資訊 heading is stripped; the paragraph text survives.
    assert record.description is not None
    assert "詳細資訊" not in record.description
    assert record.description.startswith("香港知名作家董啟章")
    assert "《心》姊妹篇" in record.description
