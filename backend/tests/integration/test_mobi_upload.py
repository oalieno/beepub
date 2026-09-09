"""MOBI/AZW3 upload: converted to an EPUB at ingest, source kept for download."""

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from tests.integration.util import create_library

FIXTURES = Path(__file__).parents[1] / "fixtures"
AZW3 = (FIXTURES / "windmill_postman.azw3").read_bytes()
MOBI7 = (FIXTURES / "ferry_last_boat.mobi").read_bytes()


@pytest.fixture
async def library_id(admin_client) -> str:
    return await create_library(admin_client)


async def upload(client, library_id: str, data: bytes, name: str) -> dict:
    response = await client.post(
        "/api/books",
        files={"file": (name, data, "application/octet-stream")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_azw3_becomes_an_epub_with_its_cover(admin_client, library_id):
    book = await upload(admin_client, library_id, AZW3, "windmill.azw3")
    assert book["format"] == "azw3"
    assert book["epub_title"] == "風車島郵差"
    assert book["epub_authors"] == ["林秋水"]
    assert book["epub_isbn"] is None
    assert book["cover_path"] is not None

    response = await admin_client.get(f"/api/books/{book['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        assert "OEBPS/content.opf" in zf.namelist()
    assert book["file_size"] == len(response.content)

    response = await admin_client.get(f"/api/books/{book['id']}/original")
    assert response.status_code == 200
    assert response.content == AZW3
    assert response.headers["content-disposition"].endswith(".azw3")

    # The Traditional Chinese rebuild is a TXT-only action.
    response = await admin_client.post(
        f"/api/books/{book['id']}/zh-conversion", json={"mode": "s2tw"}
    )
    assert response.status_code == 409


async def test_old_mobi_is_packed_into_chapters(admin_client, library_id):
    book = await upload(admin_client, library_id, MOBI7, "ferry.mobi")
    assert book["format"] == "mobi"
    assert book["epub_title"] == "渡口的最後一班船"
    assert book["cover_path"] is not None

    response = await admin_client.get(f"/api/books/{book['id']}/file")
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        names = zf.namelist()
    assert sum(n.startswith("OEBPS/text") for n in names) == 4
    assert "OEBPS/nav.xhtml" in names

    response = await admin_client.get(f"/api/books/{book['id']}/original")
    assert response.headers["content-disposition"].endswith(".mobi")


async def test_garbage_and_unknown_suffixes_are_rejected(admin_client, library_id):
    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.mobi", b"not a book" * 100, "application/octet-stream")},
        data={"library_id": library_id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid MOBI file"

    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.prc", MOBI7, "application/octet-stream")},
        data={"library_id": library_id},
    )
    assert response.status_code == 400
    assert "MOBI or AZW3" in response.json()["detail"]
