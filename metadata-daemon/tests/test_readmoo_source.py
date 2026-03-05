import asyncio

import httpx
from bs4 import BeautifulSoup

from daemon.sources.readmoo import ReadmooSource


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

        if query == "極限返航（電影書衣典藏版） 安迪．威爾（Andy Weir）":
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

        return httpx.Response(200, text=html, request=httpx.Request("GET", url, params=params))


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
          <div class='quick-btn-star'>
            <div itemprop='ratingValue' content='4.7'></div>
            共 <span itemprop='ratingCount'>237</span> 人評分
          </div>
        </body></html>
        """
        return httpx.Response(200, text=html, request=httpx.Request("GET", url, params=params))


def test_build_queries_normalizes_and_deduplicates():
    queries = ReadmooSource._build_queries("極限返航（電影書衣典藏版）", ["安迪．威爾（Andy Weir）"])

    assert queries == [
        "極限返航（電影書衣典藏版） 安迪．威爾（Andy Weir）",
        "極限返航（電影書衣典藏版）",
        "極限返航 安迪．威爾（Andy Weir）",
        "極限返航",
    ]


def test_build_queries_strips_square_bracket_subtitle():
    queries = ReadmooSource._build_queries("千年鬼【直木獎得主西條奈加最催淚之作】", [])

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
      <h4><a class='product-link' href='/book/210451960000101'>極限返航（電影書封典藏版）</a></h4>
    </body></html>
    """

    soup = BeautifulSoup(html, "html.parser")
    links = ReadmooSource._extract_book_links(soup, limit=5)

    assert links == [
        ("https://readmoo.com/book/210217152000101", "極限返航"),
        ("https://readmoo.com/book/210451960000101", "極限返航（電影書封典藏版）"),
    ]


def test_search_falls_back_to_normalized_query(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr("daemon.sources.readmoo.httpx.AsyncClient", FakeAsyncClient)

    source = ReadmooSource()
    results = asyncio.run(
        source.search("極限返航（電影書衣典藏版）", ["安迪．威爾（Andy Weir）"], None)
    )

    assert len(results) == 1
    assert results[0].title == "極限返航"
    assert results[0].url == "https://readmoo.com/book/210290289000101"
    assert FakeAsyncClient.requests == [
        ("https://readmoo.com/search/keyword", "極限返航（電影書衣典藏版） 安迪．威爾（Andy Weir）"),
        ("https://readmoo.com/search/keyword", "極限返航（電影書衣典藏版）"),
        ("https://readmoo.com/search/keyword", "極限返航 安迪．威爾（Andy Weir）"),
    ]


def test_fetch_parses_itemprop_rating_and_count(monkeypatch):
    monkeypatch.setattr("daemon.sources.readmoo.httpx.AsyncClient", FakeFetchClient)

    source = ReadmooSource()
    result = asyncio.run(source.fetch("https://readmoo.com/book/210363642000101"))

    assert result.rating == 4.7
    assert result.rating_count == 237
