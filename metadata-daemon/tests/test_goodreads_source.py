import asyncio

import httpx
from bs4 import BeautifulSoup

from daemon.sources.goodreads import GoodreadsSource


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

        if query == "極限返航 安迪．威爾":
            html = "<html><body><div>No results</div></body></html>"
        elif query == "極限返航":
            html = """
            <html><body>
              <a data-testid='bookTitle' href='/book/show/60495597-project-hail-mary'>
                Project Hail Mary
              </a>
            </body></html>
            """
        else:
            html = "<html><body></body></html>"

        return httpx.Response(
            200, text=html, request=httpx.Request("GET", url, params=params)
        )


def test_extract_book_links_supports_modern_selector_and_dedup():
    source = GoodreadsSource()
    soup = BeautifulSoup(
        """
        <html><body>
          <a data-testid='bookTitle' href='/book/show/60495597-project-hail-mary'>
            Project Hail Mary
          </a>
          <a href='/book/show/60495597-project-hail-mary'>Project Hail Mary</a>
        </body></html>
        """,
        "html.parser",
    )

    links = source._extract_book_links(soup, limit=5)

    assert links == [
        (
            "https://www.goodreads.com/book/show/60495597-project-hail-mary",
            "Project Hail Mary",
        )
    ]


def test_build_queries_strips_square_bracket_subtitle():
    queries = GoodreadsSource._build_queries(
        "千年鬼【直木獎得主西條奈加最催淚之作】", []
    )

    assert queries == [
        "千年鬼【直木獎得主西條奈加最催淚之作】",
        "千年鬼",
    ]


def test_search_falls_back_to_title_only(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr("daemon.sources.goodreads.httpx.AsyncClient", FakeAsyncClient)

    source = GoodreadsSource()
    results = asyncio.run(source.search("極限返航", ["安迪．威爾"], None))

    assert len(results) == 1
    assert (
        results[0].url
        == "https://www.goodreads.com/book/show/60495597-project-hail-mary"
    )
    assert FakeAsyncClient.requests == [
        ("https://www.goodreads.com/search", "極限返航 安迪．威爾"),
        ("https://www.goodreads.com/search", "極限返航"),
    ]
