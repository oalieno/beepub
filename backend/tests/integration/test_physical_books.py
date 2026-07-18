"""Physical (file-less) books: creation, file-endpoint gating, manual
progress, OPDS exclusion, and the ISBN prefill lookup."""

import pytest

from tests.integration.conftest import ADMIN_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration

ADMIN_BASIC = (ADMIN_CREDENTIALS["username"], ADMIN_CREDENTIALS["password"])


async def create_physical(client, library_id: str, **overrides) -> dict:
    payload = {
        "library_id": library_id,
        "title": "紙本測試書",
        "authors": ["Paper Author"],
        "isbn": "9789571234567",
        **overrides,
    }
    response = await client.post("/api/books/physical", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_physical_book(admin_client):
    library_id = await create_library(admin_client, "Physical Shelf")
    book = await create_physical(admin_client, library_id)

    assert book["format"] == "physical"
    assert book["file_size"] is None
    assert book["display_title"] == "紙本測試書"
    assert book["display_authors"] == ["Paper Author"]
    assert book["epub_isbn"] == "9789571234567"

    detail = await admin_client.get(f"/api/books/{book['id']}")
    assert detail.status_code == 200
    assert detail.json()["format"] == "physical"

    listing = await admin_client.get("/api/books/all")
    assert book["id"] in [b["id"] for b in listing.json()["items"]]


async def test_create_physical_requires_upload_permission(user_client):
    response = await user_client.post(
        "/api/books/physical",
        json={"library_id": "00000000-0000-0000-0000-000000000000", "title": "x"},
    )
    assert response.status_code == 403


async def test_file_endpoints_are_gated(admin_client):
    library_id = await create_library(admin_client)
    book = await create_physical(admin_client, library_id)

    for path in ("file", "content/OEBPS/ch1.xhtml", "images"):
        response = await admin_client.get(f"/api/books/{book['id']}/{path}")
        assert response.status_code == 409, path

    response = await admin_client.put(
        f"/api/books/{book['id']}/locations",
        json={"fingerprint": "x", "locations": '["epubcfi(/6/2!/4/2/1:0)"]'},
    )
    assert response.status_code == 409


async def test_interactions_work_without_a_file(admin_client):
    library_id = await create_library(admin_client)
    book = await create_physical(admin_client, library_id)
    book_id = book["id"]

    status_resp = await admin_client.put(
        f"/api/books/{book_id}/reading-status",
        json={"reading_status": "currently_reading"},
    )
    assert status_resp.status_code == 200

    notes_resp = await admin_client.put(
        f"/api/books/{book_id}/notes", json={"notes": "第三章看完了"}
    )
    assert notes_resp.status_code == 200

    progress_resp = await admin_client.put(
        f"/api/books/{book_id}/manual-progress", json={"percentage": 42}
    )
    assert progress_resp.status_code == 200

    reject = await admin_client.put(
        f"/api/books/{book_id}/manual-progress", json={"percentage": 101}
    )
    assert reject.status_code == 422

    interaction = (await admin_client.get(f"/api/books/{book_id}/interaction")).json()
    assert interaction["reading_status"] == "currently_reading"
    assert interaction["notes"] == "第三章看完了"
    assert interaction["reading_progress"]["percentage"] == 42


async def test_manual_progress_rejected_for_file_books(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    response = await admin_client.put(
        f"/api/books/{book['id']}/manual-progress", json={"percentage": 0.5}
    )
    assert response.status_code == 409


async def test_opds_excludes_physical_books(admin_client):
    library_id = await create_library(admin_client, "Mixed")
    epub = await upload_epub(admin_client, library_id, title="Real EPUB")
    physical = await create_physical(admin_client, library_id)

    response = await admin_client.get(
        f"/api/opds/libraries/{library_id}", auth=ADMIN_BASIC
    )
    assert response.status_code == 200
    assert epub["id"] in response.text
    assert physical["id"] not in response.text


async def test_format_filter_on_book_lists(admin_client):
    library_id = await create_library(admin_client, "Filter Lib")
    epub = await upload_epub(admin_client, library_id, title="Filter EPUB")
    physical = await create_physical(admin_client, library_id)

    scoped = await admin_client.get(
        f"/api/libraries/{library_id}/books?format=physical"
    )
    assert [b["id"] for b in scoped.json()["items"]] == [physical["id"]]
    assert scoped.json()["total"] == 1

    global_list = await admin_client.get("/api/books/all?format=physical")
    ids = [b["id"] for b in global_list.json()["items"]]
    assert physical["id"] in ids
    assert epub["id"] not in ids


async def test_delete_physical_book(admin_client):
    library_id = await create_library(admin_client)
    book = await create_physical(admin_client, library_id)

    response = await admin_client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 204
    assert (await admin_client.get(f"/api/books/{book['id']}")).status_code == 404


async def test_cover_url_host_allowlist(admin_client):
    library_id = await create_library(admin_client)
    response = await admin_client.post(
        "/api/books/physical",
        json={
            "library_id": library_id,
            "title": "SSRF probe",
            "cover_url": "https://internal.example.com/secret.png",
        },
    )
    assert response.status_code == 422


async def test_isbn_lookup_prefill(admin_client, monkeypatch):
    async def fake_lookup(isbn: str, google_api_key: str = ""):
        assert isbn == "9789571234567"
        return {
            "title": "查到的書",
            "authors": ["某作者"],
            "publisher": "某出版社",
            "description": "簡介",
            "published_date": "2020-01-01",
            "language": "zh-TW",
            "cover_url": "https://books.google.com/books/content?id=x",
        }

    monkeypatch.setattr("app.routers.books.lookup_isbn", fake_lookup)
    response = await admin_client.get("/api/books/isbn-lookup?isbn=9789571234567")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"] == "查到的書"
    assert data["cover_url"].startswith("https://books.google.com/")


async def test_isbn_lookup_not_found(admin_client, monkeypatch):
    async def fake_lookup(isbn: str, google_api_key: str = ""):
        return None

    monkeypatch.setattr("app.routers.books.lookup_isbn", fake_lookup)
    response = await admin_client.get("/api/books/isbn-lookup?isbn=0000000000")
    assert response.status_code == 404
