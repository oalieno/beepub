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
