"""Hardcover plugin: the by-slug fetch.

Hardcover can't romanize CJK titles, so their slugs are year+UUID
(e.g. 2024-8b85b922-…) — nothing in the slug identifies the book. The
old fetch re-searched the slug's words ("2024 8b85b922 …" matched Amy
Cross's "2024") and fell back to hits[0], silently linking a wrong
book on every candidate pick and pinned-URL job fetch. The fetch is a
real books(where: slug) lookup now; an unknown slug returns a bare
record, never a guess."""

import asyncio
import json

import httpx

from app.plugins.metadata.base import BookQuery
from app.plugins.metadata.hardcover import HardcoverPlugin

SLUG = "2024-8b85b922-81e9-424c-b067-2a47d646c4b8"

BOOK_PAYLOAD = {
    "data": {
        "books": [
            {
                "slug": SLUG,
                "title": "世界上最透明的故事",
                "description": "",  # the books table answers "" for none
                "release_date": "2024-01-01",
                "rating": None,
                "ratings_count": 0,
                "users_read_count": 1,
                "cached_tags": {
                    "Genre": [{"tag": "Mystery"}],
                    "Mood": [{"tag": "emotional"}],
                    "Tag": [{"tag": "Japan"}],
                    "Content Warning": [{"tag": "Death"}],
                },
                "image": {"url": "https://assets.hardcover.app/edition/x.jpeg"},
                "contributions": [
                    {"author": {"name": "Hikaru Sugii"}},
                    {"author": {"name": "杉井光"}},
                    {"author": {"name": "簡捷"}},
                ],
            }
        ]
    }
}


class BySlugClient:
    """Answers the books query for SLUG only. Any search request means
    the fetch regressed to slug re-searching — fail loudly."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, **kwargs):
        body = kwargs["json"]
        assert "books(" in body["query"], "fetch must look up by slug, not re-search"
        payload = (
            BOOK_PAYLOAD
            if body["variables"]["slug"] == SLUG
            else {"data": {"books": []}}
        )
        return httpx.Response(
            200,
            text=json.dumps(payload),
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", url),
        )


def _plugin() -> HardcoverPlugin:
    return HardcoverPlugin({"hardcover_api_token": "t"})


def test_pick_resolves_the_slug_itself(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", BySlugClient)

    record = asyncio.run(
        _plugin().resolve(BookQuery(url=SLUG, title="世界上最透明的故事"))
    )

    assert record is not None
    assert record.title == "世界上最透明的故事"
    assert record.source_url == SLUG
    assert record.authors == ["Hikaru Sugii", "杉井光", "簡捷"]
    assert record.published_date == "2024-01-01"
    assert record.cover_url == "https://assets.hardcover.app/edition/x.jpeg"
    assert record.description is None  # "" normalized
    assert record.rating is None
    assert record.rating_count is None
    # Genre+Mood+Tag, Content Warning excluded — same set the search path ships.
    assert record.tags == ["Mystery", "emotional", "Japan"]


def test_full_url_strips_prefix_before_lookup(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", BySlugClient)

    record = asyncio.run(
        _plugin().resolve(BookQuery(url=f"https://hardcover.app/books/{SLUG}"))
    )

    assert record is not None
    assert record.title == "世界上最透明的故事"


def test_unknown_slug_returns_bare_record_not_a_guess(monkeypatch):
    monkeypatch.setattr("app.plugins.metadata.base.httpx.AsyncClient", BySlugClient)

    record = asyncio.run(_plugin().resolve(BookQuery(url="some-vanished-slug")))

    assert record is not None
    assert record.source_url == "some-vanished-slug"
    assert record.title is None
    assert record.authors == []
