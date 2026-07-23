"""Pubu plugin parser tests against trimmed real pages.

The empty-search fixture keeps a recommendation cover-list on purpose:
Pubu's no-result page renders recommended books with the same article
markup as real results — only the gallery-view scoping plus the
empty-notice guard keep strangers out of the candidates."""

import asyncio
from pathlib import Path

import httpx

from app.plugins.metadata.base import BookQuery
from app.plugins.metadata.pubu import PubuPlugin

SEARCH_FIXTURE = Path(__file__).parent / "fixtures" / "pubu_search.html"
EMPTY_FIXTURE = Path(__file__).parent / "fixtures" / "pubu_search_empty.html"
PRODUCT_FIXTURE = Path(__file__).parent / "fixtures" / "pubu_product.html"


def test_search_items_parse_title_authors_store_cover():
    candidates = PubuPlugin._parse_search_items(
        SEARCH_FIXTURE.read_text(encoding="utf-8"), limit=5
    )

    assert len(candidates) == 2
    first = candidates[0]
    assert first.title == "世界上最透明的故事2"
    assert first.url == "https://www.pubu.com.tw/ebook/628595"
    assert first.authors == ["杉井光"]
    assert first.publisher == "皇冠"
    assert first.cover_url and first.cover_url.startswith("https://res")


def test_empty_page_recommendations_never_become_candidates():
    candidates = PubuPlugin._parse_search_items(
        EMPTY_FIXTURE.read_text(encoding="utf-8"), limit=5
    )
    assert candidates == []


def test_book_page_parses_ld_date_crumbs_and_full_description():
    record = PubuPlugin._parse_book_page(
        PRODUCT_FIXTURE.read_text(encoding="utf-8"),
        "https://www.pubu.com.tw/ebook/628595",
    )

    assert record.title == "世界上最透明的故事2"
    assert record.authors == ["杉井光"]
    assert record.publisher == "皇冠"
    assert record.language == "zh-TW"
    assert record.published_date == "2025/11/26"
    assert record.cover_url and record.cover_url.startswith("https://res")
    assert record.tags == ["書刊", "文學小說", "小說", "懸疑/推理小說"]
    # The rating widget reads 「5.0分，5則評分」; comments are JS-loaded
    # so reviews are never provided.
    assert record.rating == 5.0
    assert record.rating_count == 5
    assert record.reviews is None
    # The full server-rendered intro, not the ~190-char og: teaser.
    assert record.description is not None
    assert len(record.description) > 500
    assert record.description.startswith("這本書還可以出第 2 集？！")


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, params: dict | None = None):
        if "/ebook/" in url:
            text = PRODUCT_FIXTURE.read_text(encoding="utf-8")
        elif (params or {}).get("q") == "no such book":
            text = EMPTY_FIXTURE.read_text(encoding="utf-8")
        else:
            text = SEARCH_FIXTURE.read_text(encoding="utf-8")
        return httpx.Response(
            200,
            text=text,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )


def test_resolve_title_lands_on_the_book_page(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(PubuPlugin().resolve(BookQuery(title="世界上最透明的故事2")))

    assert record is not None
    assert record.title == "世界上最透明的故事2"
    assert record.published_date == "2025/11/26"


def test_resolve_no_hits_returns_none(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    assert asyncio.run(PubuPlugin().resolve(BookQuery(title="no such book"))) is None


def test_pick_fetches_by_bare_ebook_id(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", FakeAsyncClient)

    record = asyncio.run(PubuPlugin().resolve(BookQuery(url="628595")))

    assert record is not None
    assert record.source_url == "https://www.pubu.com.tw/ebook/628595"
    assert record.title == "世界上最透明的故事2"
