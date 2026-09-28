"""Server-side OPDS catalogs: admin-managed list, proxy, import."""

import base64

import httpx
import pytest

from app.routers import opds_catalogs
from app.services.opds_fetch import OpdsFetcher
from tests.factories.epub import build_epub
from tests.integration.util import create_library

pytestmark = pytest.mark.integration

ROOT = "https://books.example.org/opds"
FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Harbour Stacks</title></feed>"""
EPUB = build_epub(
    title="Lamplighter's Almanac",
    identifier="urn:uuid:5f8e2a70-0000-4000-8000-00000000cafe",
)


@pytest.fixture
def upstream(monkeypatch):
    """Route the server's catalog fetches to an in-process fake catalog."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/opds":
            return httpx.Response(302, headers={"location": "/opds/root"})
        if path == "/opds/root":
            return httpx.Response(
                200, text=FEED, headers={"content-type": "application/atom+xml"}
            )
        if path == "/covers/1.png":
            return httpx.Response(
                200, content=b"\x89PNG", headers={"content-type": "image/png"}
            )
        if path == "/download/1":
            return httpx.Response(
                200,
                content=EPUB,
                headers={
                    "content-type": "application/octet-stream",
                    "content-disposition": 'attachment; filename="almanac.epub"',
                },
            )
        return httpx.Response(404)

    class Fetcher(OpdsFetcher):
        def __init__(self, url, creds, block, transport=None):
            super().__init__(url, creds, block, httpx.MockTransport(handler))

    monkeypatch.setattr(opds_catalogs, "OpdsFetcher", Fetcher)
    return seen


async def _add(client, **extra) -> dict:
    response = await client.post(
        "/api/opds-catalogs", json={"name": "Harbour Stacks", "url": ROOT, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_only_admins_manage_catalogs(admin_client, user_client):
    denied = await user_client.post(
        "/api/opds-catalogs", json={"name": "x", "url": ROOT}
    )
    assert denied.status_code == 403

    catalog = await _add(admin_client, username="reader", password="s3cret")
    assert catalog["url"] == ROOT
    assert catalog["username"] == "reader"
    assert "password" not in catalog

    listed = (await user_client.get("/api/opds-catalogs")).json()
    assert [c["id"] for c in listed] == [catalog["id"]]
    assert listed[0]["username"] is None  # readers don't see the account
    assert listed[0]["has_credentials"] is True

    for call in (
        user_client.put(
            f"/api/opds-catalogs/{catalog['id']}", json={"name": "y", "url": ROOT}
        ),
        user_client.delete(f"/api/opds-catalogs/{catalog['id']}"),
    ):
        assert (await call).status_code == 403


async def test_update_keeps_the_password_unless_given(admin_client, upstream):
    catalog = await _add(admin_client, username="reader", password="s3cret")
    path = f"/api/opds-catalogs/{catalog['id']}"
    response = await admin_client.put(
        path, json={"name": "Renamed", "url": ROOT, "username": "reader"}
    )
    assert response.json()["name"] == "Renamed"

    await admin_client.get(f"{path}/feed")
    expected = "Basic " + base64.b64encode(b"reader:s3cret").decode()
    assert upstream[-1].headers["authorization"] == expected

    # No username means no credentials at all.
    await admin_client.put(path, json={"name": "Renamed", "url": ROOT})
    assert (await admin_client.get(path)).json()["has_credentials"] is False


async def test_urls_are_kept_as_entered(admin_client):
    # Some servers 403 without the trailing slash.
    catalog = await _add(admin_client, url=" https://books.example.org/g.opds/ ")
    assert catalog["url"] == "https://books.example.org/g.opds/"


async def test_rejects_non_http_urls(admin_client):
    response = await admin_client.post(
        "/api/opds-catalogs", json={"name": "x", "url": "file:///etc/passwd"}
    )
    assert response.status_code == 422


async def test_feed_proxy_returns_the_body_and_final_url(
    admin_client, user_client, upstream
):
    catalog = await _add(admin_client)
    response = await user_client.get(f"/api/opds-catalogs/{catalog['id']}/feed")
    assert response.status_code == 200, response.text
    assert response.json() == {"url": ROOT + "/root", "body": FEED}

    outside = await user_client.get(
        f"/api/opds-catalogs/{catalog['id']}/feed",
        params={"url": "http://169.254.169.254/latest/meta-data"},
    )
    assert outside.status_code == 403


async def test_image_proxy(admin_client, upstream):
    catalog = await _add(admin_client)
    response = await admin_client.get(
        f"/api/opds-catalogs/{catalog['id']}/image",
        params={"url": "https://books.example.org/covers/1.png"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    not_image = await admin_client.get(
        f"/api/opds-catalogs/{catalog['id']}/image", params={"url": ROOT + "/root"}
    )
    assert not_image.status_code == 415


async def test_import_adds_the_book_once(admin_client, upstream):
    catalog = await _add(admin_client)
    library_id = await create_library(admin_client, "OPDS Imports")
    body = {
        "url": "https://books.example.org/download/1",
        "library_id": library_id,
        "title": "Lamplighter's Almanac",
        "type": "application/epub+zip",
    }
    path = f"/api/opds-catalogs/{catalog['id']}/import"

    first = await admin_client.post(path, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "imported"
    book = first.json()["book"]
    assert book["format"] == "epub"

    again = await admin_client.post(path, json=body)
    assert again.json() == {"status": "duplicate", "book": again.json()["book"]}
    assert again.json()["book"]["id"] == book["id"]


async def test_import_needs_upload_permission(admin_client, user_client, upstream):
    catalog = await _add(admin_client)
    library_id = await create_library(admin_client, "OPDS Imports")
    response = await user_client.post(
        f"/api/opds-catalogs/{catalog['id']}/import",
        json={"url": ROOT + "/download/1", "library_id": library_id},
    )
    assert response.status_code == 403
