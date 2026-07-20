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
