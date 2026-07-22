"""Per-plugin enable toggles: settings round-trip, and the manual-link
endpoint refusing disabled sources."""

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


async def test_toggle_round_trips_through_admin_settings(admin_client):
    resp = await admin_client.get("/api/admin/settings")
    assert resp.status_code == 200
    settings = resp.json()
    # Registry-derived defaults are present and enabled.
    assert settings["metadata_source_readmoo_enabled"] == "true"
    assert settings["metadata_source_books_tw_enabled"] == "true"
    assert settings["metadata_job_sources"] == ""

    resp = await admin_client.put(
        "/api/admin/settings",
        json={
            "metadata_source_readmoo_enabled": "false",
            "metadata_job_sources": "goodreads, google_books",
        },
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["metadata_source_readmoo_enabled"] == "false"
    assert updated["metadata_job_sources"] == "goodreads, google_books"


async def test_sources_endpoint_reflects_registry_and_settings(
    admin_client, user_client
):
    # Any authenticated user can read the registry (the frontend builds
    # its source knowledge from it).
    resp = await user_client.get("/api/metadata/sources")
    assert resp.status_code == 200
    sources = {s["name"]: s for s in resp.json()["sources"]}
    assert set(sources) == {
        "goodreads",
        "readmoo",
        "google_books",
        "hardcover",
        "books_tw",
        "open_library",
    }

    goodreads = sources["goodreads"]
    assert goodreads["enabled"] is True
    assert goodreads["in_job"] is True
    assert goodreads["url_prefix"] == "https://www.goodreads.com/book/show/"
    assert "rating" in goodreads["provides"]

    books_tw = sources["books_tw"]
    assert books_tw["label"] == "博客來"
    assert books_tw["accepts"] == ["isbn"]
    assert books_tw["url_prefix"] is None
    assert books_tw["kind"] == "scraper"

    google = sources["google_books"]
    assert google["configured"] is False  # no API key set in tests
    assert google["setting_keys"] == ["google_books_api_key"]

    # Toggling + job list flips the flags.
    resp = await admin_client.put(
        "/api/admin/settings",
        json={
            "metadata_source_readmoo_enabled": "false",
            "metadata_job_sources": "goodreads",
        },
    )
    assert resp.status_code == 200

    resp = await admin_client.get("/api/metadata/sources")
    sources = {s["name"]: s for s in resp.json()["sources"]}
    assert sources["readmoo"]["enabled"] is False
    assert sources["readmoo"]["in_job"] is False
    assert sources["goodreads"]["in_job"] is True
    assert sources["google_books"]["in_job"] is False


async def test_manual_link_rejects_disabled_and_unknown_sources(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    book_id = book["id"]

    url = "https://www.goodreads.com/book/show/60495597"

    # Unknown source name → 400 listing the registry.
    resp = await admin_client.put(
        f"/api/books/{book_id}/external/nonexistent/url",
        json={"source_url": url},
    )
    assert resp.status_code == 400

    # Sources without manual-linking support are refused.
    resp = await admin_client.put(
        f"/api/books/{book_id}/external/books_tw/url",
        json={"source_url": "https://www.books.com.tw/products/0010752879"},
    )
    assert resp.status_code == 400

    # Disabled source → 409.
    resp = await admin_client.put(
        "/api/admin/settings",
        json={"metadata_source_goodreads_enabled": "false"},
    )
    assert resp.status_code == 200
    resp = await admin_client.put(
        f"/api/books/{book_id}/external/goodreads/url",
        json={"source_url": url},
    )
    assert resp.status_code == 409

    # Re-enabled → the link goes through (refetch is queued async).
    resp = await admin_client.put(
        "/api/admin/settings",
        json={"metadata_source_goodreads_enabled": "true"},
    )
    assert resp.status_code == 200
    resp = await admin_client.put(
        f"/api/books/{book_id}/external/goodreads/url",
        json={"source_url": url},
    )
    assert resp.status_code == 200
    assert resp.json()["source_url"] == url


async def test_single_source_refetch_carries_book_clues(admin_client, monkeypatch):
    """The rebind/pinned refetch must echo the book's own clues next to
    the pinned URL — a url-only query archives a degraded record for
    sources that need their search-side context (google's merge)."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    book_id = book["id"]

    resp = await admin_client.put(
        f"/api/books/{book_id}/external/goodreads/url",
        json={"source_url": "https://www.goodreads.com/book/show/60495597"},
    )
    assert resp.status_code == 200

    from app.plugins.metadata.base import BookRecord
    from app.plugins.metadata.goodreads import GoodreadsPlugin
    from app.tasks.metadata import _run_fetch_metadata_source

    captured = {}

    async def fake_resolve(self, query):
        captured["query"] = query
        return BookRecord(source_url=query.url, title="stub")

    monkeypatch.setattr(GoodreadsPlugin, "resolve", fake_resolve)
    await _run_fetch_metadata_source(book_id, "goodreads")

    query = captured["query"]
    assert query.url == "https://www.goodreads.com/book/show/60495597"
    assert query.title, "the book's title must ride along with the pinned URL"


async def test_source_stats_tallies_and_health(admin_client, user_client, monkeypatch):
    """The stats endpoint: admin-only, archive tallies from
    external_metadata, and the Redis health hash written at the resolve
    chokepoints (success resets the failure counter, errors bump it,
    rate limits never count as failures)."""
    resp = await user_client.get("/api/metadata/sources/stats")
    assert resp.status_code == 403

    # A blank install still answers, with every source zeroed.
    resp = await admin_client.get("/api/metadata/sources/stats")
    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["goodreads"]["books_found"] == 0
    assert stats["goodreads"]["last_success_at"] is None

    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    book_id = book["id"]

    resp = await admin_client.put(
        f"/api/books/{book_id}/external/goodreads/url",
        json={"source_url": "https://www.goodreads.com/book/show/60495597"},
    )
    assert resp.status_code == 200

    from app.plugins.metadata.base import BookQuery, BookRecord, RateLimitError
    from app.plugins.metadata.goodreads import GoodreadsPlugin
    from app.services.metadata_fetch import cached_resolve
    from app.tasks.metadata import _run_fetch_metadata_source

    async def ok_resolve(self, query):
        return BookRecord(source_url=query.url, title="stub")

    monkeypatch.setattr(GoodreadsPlugin, "resolve", ok_resolve)
    await _run_fetch_metadata_source(book_id, "goodreads")

    resp = await admin_client.get("/api/metadata/sources/stats")
    goodreads = resp.json()["stats"]["goodreads"]
    assert goodreads["books_found"] == 1
    assert goodreads["books_not_found"] == 0
    assert goodreads["last_fetched_at"] is not None
    assert goodreads["last_success_at"] is not None
    assert goodreads["consecutive_failures"] == 0

    # Failures through the shared resolve path bump the counter and
    # keep the error message; rate limits are tracked separately.
    async def broken_resolve(self, query):
        raise RuntimeError("scraper layout changed")

    monkeypatch.setattr(GoodreadsPlugin, "resolve", broken_resolve)
    plugin = GoodreadsPlugin({})
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cached_resolve(plugin, BookQuery(title="whatever"))

    async def limited_resolve(self, query):
        raise RateLimitError("goodreads")

    monkeypatch.setattr(GoodreadsPlugin, "resolve", limited_resolve)
    with pytest.raises(RateLimitError):
        await cached_resolve(plugin, BookQuery(title="whatever"))

    resp = await admin_client.get("/api/metadata/sources/stats")
    goodreads = resp.json()["stats"]["goodreads"]
    assert goodreads["consecutive_failures"] == 2
    assert "scraper layout changed" in goodreads["last_error"]
    assert goodreads["last_ratelimited_at"] is not None

    # One success heals the streak (but keeps the error history).
    monkeypatch.setattr(GoodreadsPlugin, "resolve", ok_resolve)
    await cached_resolve(plugin, BookQuery(title="whatever"))

    resp = await admin_client.get("/api/metadata/sources/stats")
    goodreads = resp.json()["stats"]["goodreads"]
    assert goodreads["consecutive_failures"] == 0
    assert goodreads["last_error_at"] is not None


async def test_job_sources_none_sentinel_round_trips(admin_client):
    """'-' = background fetch off entirely; empty string still means
    the default (all enabled sources)."""
    resp = await admin_client.put(
        "/api/admin/settings", json={"metadata_job_sources": "-"}
    )
    assert resp.status_code == 200

    resp = await admin_client.get("/api/metadata/sources")
    sources = resp.json()["sources"]
    assert all(s["in_job"] is False for s in sources)
    assert all(s["enabled"] is True for s in sources)


async def test_ratelimit_resume_is_announced_and_cancellable(admin_client):
    """A 429 arms exactly one announced continuation (NX dedup), the
    jobs page exposes its ETA, cancelling deletes it, and the fired
    task honours a cancel by not starting a run."""
    import redis.asyncio as aioredis

    from app.config import settings as app_config
    from app.services.job_queue import get_generation
    from app.tasks.metadata import (
        RESUME_KEY,
        _resume_backfill,
        _set_rate_limited,
    )

    client = aioredis.from_url(app_config.redis_url, decode_responses=True)
    try:
        await _set_rate_limited(client, "goodreads")
        eta = await client.get(RESUME_KEY)
        assert eta is not None

        # NX dedup: a second 429 in the same window keeps the first ETA.
        await _set_rate_limited(client, "readmoo")
        assert await client.get(RESUME_KEY) == eta

        resp = await admin_client.get("/api/admin/jobs")
        jobs = {j["key"]: j for j in resp.json()["jobs"]}
        assert jobs["metadata_backfill"]["resume_at"] == eta
        assert all(
            j["resume_at"] is None for k, j in jobs.items() if k != "metadata_backfill"
        )

        # Cancel: key gone, and the fired task no-ops instead of
        # starting a run.
        resp = await admin_client.delete("/api/admin/jobs/metadata_backfill/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert await client.get(RESUME_KEY) is None

        gen_before = await get_generation("metadata_backfill")
        await _resume_backfill()
        assert await get_generation("metadata_backfill") == gen_before

        # Uncancelled: the claim consumes the key and starts a run.
        await _set_rate_limited(client, "goodreads")
        await _resume_backfill()
        assert await get_generation("metadata_backfill") == gen_before + 1
        assert await client.get(RESUME_KEY) is None
    finally:
        await client.aclose()
