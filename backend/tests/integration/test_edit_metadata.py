"""Edit-metadata backend surface: per-field provenance (field_sources),
cover replacement, and the record store exposed per book."""

import io

import pytest

from tests.integration.util import create_library

pytestmark = pytest.mark.integration


async def _create_book(client) -> dict:
    library_id = await create_library(client, "Edit Meta Shelf")
    response = await client.post(
        "/api/books/physical",
        json={"library_id": library_id, "title": "編輯測試書"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 6), "red").save(buf, "PNG")
    return buf.getvalue()


async def test_field_sources_round_trip(admin_client):
    book = await _create_book(admin_client)
    response = await admin_client.put(
        f"/api/books/{book['id']}/metadata",
        json={
            "description": "來源描述",
            "field_sources": {"description": "readmoo", "cover": "google_books"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["description"] == "來源描述"
    assert body["field_sources"] == {"description": "readmoo", "cover": "google_books"}

    # The map replaces wholesale when sent; omitting it leaves it alone.
    response = await admin_client.put(
        f"/api/books/{book['id']}/metadata",
        json={"field_sources": {"description": "manual"}},
    )
    assert response.json()["field_sources"] == {"description": "manual"}
    response = await admin_client.put(
        f"/api/books/{book['id']}/metadata",
        json={"title": "改個書名"},
    )
    assert response.json()["field_sources"] == {"description": "manual"}


async def test_field_sources_rejects_unknown_keys(admin_client):
    book = await _create_book(admin_client)
    response = await admin_client.put(
        f"/api/books/{book['id']}/metadata",
        json={"field_sources": {"word_count": "manual"}},
    )
    assert response.status_code == 422


async def test_external_rows_expose_the_stored_record(admin_client):
    book = await _create_book(admin_client)
    # Binding a URL creates the row; the record itself stays NULL until
    # a fetch succeeds — the field must be present either way.
    response = await admin_client.put(
        f"/api/books/{book['id']}/external/readmoo/url",
        json={"source_url": "https://readmoo.com/book/210466370000101"},
    )
    assert response.status_code == 200, response.text
    rows = (await admin_client.get(f"/api/books/{book['id']}/external")).json()
    readmoo = next(r for r in rows if r["source"] == "readmoo")
    assert "record" in readmoo


async def test_cover_replace_from_url(admin_client, monkeypatch, tmp_path):
    from app.services import storage

    monkeypatch.setattr(storage.settings, "covers_dir", str(tmp_path))

    async def fake_download(url, dest_path):
        return storage.save_cover_bytes(_png_bytes(), dest_path)

    monkeypatch.setattr("app.routers.books.download_cover", fake_download)

    book = await _create_book(admin_client)
    response = await admin_client.put(
        f"/api/books/{book['id']}/cover",
        json={"url": "https://cdn.readmoo.com/cover/x/test_460x580.jpg"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["cover_path"]

    cover = await admin_client.get(f"/api/books/{book['id']}/cover")
    assert cover.status_code == 200


async def test_cover_replace_rejects_foreign_hosts(admin_client):
    book = await _create_book(admin_client)
    response = await admin_client.put(
        f"/api/books/{book['id']}/cover",
        json={"url": "https://evil.example.com/cover.jpg"},
    )
    assert response.status_code == 422


async def test_cover_upload_multipart(admin_client, monkeypatch, tmp_path):
    from app.services import storage

    monkeypatch.setattr(storage.settings, "covers_dir", str(tmp_path))

    book = await _create_book(admin_client)
    response = await admin_client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["cover_path"]

    garbage = await admin_client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("evil.png", b"not an image", "image/png")},
    )
    assert garbage.status_code == 422


async def test_cover_endpoints_require_admin(admin_client, user_client):
    book = await _create_book(admin_client)
    response = await user_client.put(
        f"/api/books/{book['id']}/cover",
        json={"url": "https://cdn.readmoo.com/cover/x/test_460x580.jpg"},
    )
    assert response.status_code == 403
    response = await user_client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 403
