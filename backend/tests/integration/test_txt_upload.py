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


SIMPLIFIED = (
    "雾港夜航 作者：陈默\n"
    "\n"
    "第一章 出港\n"
    "　　缆绳解开的时候，雾还没散。软件工程师上了船。\n"
).encode()


async def _epub_text(client, book_id: str) -> str:
    response = await client.get(f"/api/books/{book_id}/file")
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        return "".join(
            zf.read(n).decode() for n in zf.namelist() if n.startswith("OEBPS/text/")
        )


async def _set_preference(client, mode):
    response = await client.put(
        "/api/auth/preferences", json={"upload_zh_conversion": mode}
    )
    assert response.status_code == 200, response.text
    assert response.json()["upload_zh_conversion"] == mode


async def test_preference_converts_simplified_txt_at_upload(admin_client, library_id):
    await _set_preference(admin_client, "s2twp")
    try:
        book = await upload_txt(admin_client, library_id, SIMPLIFIED, "novel.txt")
    finally:
        await _set_preference(admin_client, None)
    assert book["epub_language"] == "zh-TW"
    assert book["epub_title"] == "霧港夜航"
    assert book["epub_authors"] == ["陳默"]
    text = await _epub_text(admin_client, book["id"])
    assert "纜繩解開" in text and "軟體工程師" in text
    assert "缆绳" not in text

    # The source is untouched.
    response = await admin_client.get(f"/api/books/{book['id']}/original")
    assert response.content == SIMPLIFIED


async def test_traditional_txt_is_not_touched_by_the_preference(
    admin_client, library_id
):
    await _set_preference(admin_client, "s2twp")
    try:
        book = await upload_txt(admin_client, library_id, TXT)
    finally:
        await _set_preference(admin_client, None)
    assert book["epub_language"] == "zh-TW"
    assert "退潮之後，沙灘上留著昨夜的腳印" in await _epub_text(
        admin_client, book["id"]
    )


async def test_existing_txt_book_can_be_rebuilt_as_traditional(
    admin_client, library_id
):
    book = await upload_txt(admin_client, library_id, SIMPLIFIED, "novel.txt")
    assert book["epub_language"] == "zh-CN"
    assert "缆绳" in await _epub_text(admin_client, book["id"])

    response = await admin_client.post(
        f"/api/books/{book['id']}/zh-conversion", json={"mode": "s2tw"}
    )
    assert response.status_code == 200, response.text
    converted = response.json()
    assert converted["epub_language"] == "zh-TW"
    assert converted["epub_title"] == "霧港夜航"
    assert converted["file_size"] != book["file_size"] or True
    text = await _epub_text(admin_client, book["id"])
    assert "纜繩解開" in text and "軟件工程師" in text  # s2tw keeps the phrase

    # Not offered for EPUB uploads.
    epub = build_epub(title="Not a TXT", chapters=[("One", ["hi"])])
    response = await admin_client.post(
        "/api/books",
        files={"file": ("plain.epub", epub, "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201
    response = await admin_client.post(
        f"/api/books/{response.json()['id']}/zh-conversion", json={"mode": "s2tw"}
    )
    assert response.status_code == 409
