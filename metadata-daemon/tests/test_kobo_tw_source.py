import asyncio

import httpx

from daemon.sources.kobo_tw import KoboTWSource


class FakeChallengeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, params: dict | None = None):
        html = "<html><head><title>Challenged | Kobo.com</title></head><body>bot check</body></html>"
        return httpx.Response(403, text=html, request=httpx.Request("GET", url, params=params))


def test_search_returns_empty_when_challenged(monkeypatch):
    monkeypatch.setattr("daemon.sources.kobo_tw.httpx.AsyncClient", FakeChallengeClient)

    source = KoboTWSource()
    results = asyncio.run(source.search("極限返航", ["安迪．威爾"], None))

    assert results == []


def test_fetch_returns_empty_result_when_challenged(monkeypatch):
    monkeypatch.setattr("daemon.sources.kobo_tw.httpx.AsyncClient", FakeChallengeClient)

    source = KoboTWSource()
    result = asyncio.run(source.fetch("https://www.kobo.com/tw/zh/ebook/foo"))

    assert result.source_url == "https://www.kobo.com/tw/zh/ebook/foo"
    assert result.rating is None
    assert result.rating_count is None
