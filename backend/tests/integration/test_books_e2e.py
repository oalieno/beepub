"""Book lifecycle through the real pipeline: library → upload → list →
download → delete, with actual EPUB parsing and file storage."""

import pytest

from tests.factories.epub import build_epub

pytestmark = pytest.mark.integration


@pytest.fixture
async def library_id(admin_client) -> str:
    response = await admin_client.post("/api/libraries", json={"name": "Main"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def upload(admin_client, library_id: str, epub: bytes) -> dict:
    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.epub", epub, "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_upload_parses_metadata_and_cover(admin_client, library_id):
    epub = build_epub(title="紅樓夢", authors=("曹雪芹",), language="zh", vertical=True)
    book = await upload(admin_client, library_id, epub)
    assert book["epub_title"] == "紅樓夢"
    assert book["epub_authors"] == ["曹雪芹"]
    assert book["epub_language"] == "zh"
    assert book["cover_path"] is not None


async def test_uploaded_book_is_listed_and_downloadable(admin_client, library_id):
    epub = build_epub(title="Listed Book")
    book = await upload(admin_client, library_id, epub)

    response = await admin_client.get("/api/books/all")
    assert response.status_code == 200
    listing = response.json()
    assert listing["total"] == 1
    assert [b["epub_title"] for b in listing["items"]] == ["Listed Book"]

    response = await admin_client.get(f"/api/books/{book['id']}/file")
    assert response.status_code == 200
    assert response.content == epub


async def test_upload_without_library_is_rejected(admin_client):
    # Regression: orphan uploads used to return 201 but the book was
    # unreachable from every listing (all of them join library_books).
    epub = build_epub()
    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.epub", epub, "application/epub+zip")},
        data={"library_id": ""},
    )
    assert response.status_code == 422


async def test_corrupt_epub_is_rejected_without_leftovers(admin_client, library_id):
    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.epub", b"not an epub at all", "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 400

    response = await admin_client.get("/api/books/all")
    assert response.json()["total"] == 0


async def test_delete_removes_book_everywhere(admin_client, library_id):
    book = await upload(admin_client, library_id, build_epub())

    response = await admin_client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 204

    response = await admin_client.get("/api/books/all")
    assert response.json()["total"] == 0
    response = await admin_client.get(f"/api/books/{book['id']}/file")
    assert response.status_code == 404
