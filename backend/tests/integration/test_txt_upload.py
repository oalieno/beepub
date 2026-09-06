"""TXT upload: converted to an EPUB at ingest, source kept for download."""

import zipfile
from io import BytesIO

import pytest

from tests.factories.epub import build_epub
from tests.integration.util import create_library

TXT = (
    "《潮汐鐘樓手記》\n"
    "作者：林未晞\n"
    "\n"
    "第一卷 潮聲\n"
    "第一章 退潮\n"
    "　　退潮之後，沙灘上留著昨夜的腳印。\n"
    "第二章 鐘擺\n"
    "　　鐘擺停在三點十七分。\n"
).encode()


@pytest.fixture
async def library_id(admin_client) -> str:
    return await create_library(admin_client)


async def upload_txt(client, library_id: str, data: bytes, name="novel.txt") -> dict:
    response = await client.post(
        "/api/books",
        files={"file": (name, data, "text/plain")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_txt_becomes_a_chaptered_epub(admin_client, library_id):
    book = await upload_txt(admin_client, library_id, TXT)
    assert book["format"] == "txt"
    assert book["epub_title"] == "潮汐鐘樓手記"
    assert book["epub_authors"] == ["林未晞"]
    assert book["epub_language"] == "zh-TW"
    assert book["cover_path"] is None

    # /file is the EPUB the reader and the app download.
    response = await admin_client.get(f"/api/books/{book['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        names = zf.namelist()
    assert "OEBPS/nav.xhtml" in names
    assert sum(n.startswith("OEBPS/text/") for n in names) == 2
    assert book["file_size"] == len(response.content)

    # /original is the file as uploaded.
    response = await admin_client.get(f"/api/books/{book['id']}/original")
    assert response.status_code == 200
    assert response.content == TXT
    assert "attachment" in response.headers["content-disposition"]
    assert ".txt" in response.headers["content-disposition"]


async def test_epub_books_have_no_original(admin_client, library_id):
    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.epub", build_epub(), "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201
    book = response.json()
    assert book["format"] == "epub"
    response = await admin_client.get(f"/api/books/{book['id']}/original")
    assert response.status_code == 404


async def test_delete_removes_both_files(admin_client, library_id):
    book = await upload_txt(admin_client, library_id, TXT)
    response = await admin_client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 204
    for path in ("file", "original"):
        response = await admin_client.get(f"/api/books/{book['id']}/{path}")
        assert response.status_code == 404


async def test_bulk_upload_takes_txt_alongside_epub(admin_client, library_id):
    response = await admin_client.post(
        "/api/books/bulk",
        files=[
            ("files", ("a.epub", build_epub(title="A"), "application/epub+zip")),
            ("files", ("b.txt", TXT, "text/plain")),
            ("files", ("c.mobi", b"not supported", "application/octet-stream")),
        ],
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text
    assert sorted(b["format"] for b in response.json()) == ["epub", "txt"]


async def test_unsupported_and_empty_uploads_are_rejected(admin_client, library_id):
    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.mobi", b"x", "application/octet-stream")},
        data={"library_id": library_id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Only EPUB or TXT files are supported"

    response = await admin_client.post(
        "/api/books",
        files={"file": ("blank.txt", b"\n\n", "text/plain")},
        data={"library_id": library_id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The TXT file has no text"

    response = await admin_client.get("/api/books/all")
    assert response.json()["total"] == 0
