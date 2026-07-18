"""Unit tests for the framework resolve cache (cached_resolve)."""

import asyncio

from app.plugins.metadata.base import BookQuery, BookRecord, Clue, MetadataPlugin
from app.services import metadata_fetch
from app.services.metadata_fetch import _clue_fingerprint, cached_resolve


class FakeRedis:
    store: dict[str, str] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def get(self, key):
        return self.__class__.store.get(key)

    async def set(self, key, value, ex=None):
        self.__class__.store[key] = value

    async def aclose(self):
        pass


class CountingPlugin(MetadataPlugin):
    name = "counting"
    label = "Counting"
    accepts = frozenset({Clue.ISBN, Clue.TITLE})
    provides = frozenset({"title"})

    calls = 0
    result: BookRecord | None = None

    async def resolve(self, query: BookQuery) -> BookRecord | None:
        type(self).calls += 1
        return type(self).result


def _setup(monkeypatch, result: BookRecord | None):
    FakeRedis.store = {}
    CountingPlugin.calls = 0
    CountingPlugin.result = result
    monkeypatch.setattr(metadata_fetch.aioredis, "from_url", lambda url: FakeRedis())
    return CountingPlugin({})


def test_found_records_are_cached_and_round_trip(monkeypatch):
    record = BookRecord(title="神", authors=["董啟章"], tags=["fiction"], rating=4.4)
    plugin = _setup(monkeypatch, record)
    query = BookQuery(isbn="9789570849523")

    first = asyncio.run(cached_resolve(plugin, query))
    second = asyncio.run(cached_resolve(plugin, query))

    assert CountingPlugin.calls == 1  # second call was a cache hit
    assert first == record
    assert second == record  # full round-trip through JSON


def test_not_found_is_never_cached(monkeypatch):
    plugin = _setup(monkeypatch, None)
    query = BookQuery(isbn="0000000000000")

    assert asyncio.run(cached_resolve(plugin, query)) is None
    assert asyncio.run(cached_resolve(plugin, query)) is None
    assert CountingPlugin.calls == 2
    assert FakeRedis.store == {}


def test_fingerprint_uses_most_precise_clue():
    # An isbn-only interactive lookup and the richer background-job
    # query (same isbn + title/authors) must share a cache entry.
    isbn_only = BookQuery(isbn="9789570849523")
    job_query = BookQuery(title="神", authors=["董啟章"], isbn="9789570849523")
    assert _clue_fingerprint(isbn_only) == _clue_fingerprint(job_query)

    # Without an isbn, title/authors matter (normalized).
    a = BookQuery(title="  神 ", authors=["董啟章 "])
    b = BookQuery(title="神", authors=["董啟章"])
    c = BookQuery(title="心")
    assert _clue_fingerprint(a) == _clue_fingerprint(b)
    assert _clue_fingerprint(b) != _clue_fingerprint(c)

    # A url outranks everything.
    u = BookQuery(url="https://readmoo.com/book/1", isbn="9789570849523")
    assert _clue_fingerprint(u) != _clue_fingerprint(isbn_only)


def test_cache_failure_degrades_to_live_resolve(monkeypatch):
    record = BookRecord(title="X")
    plugin = _setup(monkeypatch, record)

    def broken_from_url(url):
        raise RuntimeError("redis down")

    monkeypatch.setattr(metadata_fetch.aioredis, "from_url", broken_from_url)
    assert asyncio.run(cached_resolve(plugin, BookQuery(isbn="1234567890"))) == record
    assert CountingPlugin.calls == 1
