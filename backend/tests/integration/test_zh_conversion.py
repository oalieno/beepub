"""Simplified-to-Traditional conversion of uploaded books: detected at
upload and asked about, never done unasked; done from the book page,
highlights included."""

import zipfile
from io import BytesIO

import pytest

from tests.factories.epub import build_epub
from tests.integration.util import create_library

SIMPLIFIED_EPUB = build_epub(
    title="雾港夜航",
    authors=("陈默",),
    language="zh-CN",
    chapters=[
        ("序", ["没有灯的船在雾里等潮。" * 3]),
        ("第一章", ["他剪了头发，用U盘拷了视频。缆绳解开的时候，软件工程师上了船。"]),
    ],
)
TRADITIONAL_EPUB = build_epub(
    title="潮汐鐘樓手記",
    language="zh",
    chapters=[("第一章", ["退潮之後，沙灘上留著昨夜的腳印。" * 3])],
)


@pytest.fixture
async def library_id(admin_client) -> str:
    return await create_library(admin_client)


async def _upload(client, library_id: str, data: bytes, name="book.epub") -> dict:
    response = await client.post(
        "/api/books",
        files={"file": (name, data, "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _chapter(client, book_id: str, name="OEBPS/chapter2.xhtml") -> str:
    response = await client.get(f"/api/books/{book_id}/file")
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        return zf.read(name).decode()


async def test_simplified_upload_is_reported_not_converted(admin_client, library_id):
    book = await _upload(admin_client, library_id, SIMPLIFIED_EPUB)
    assert book["zh_simplified"] is True
    assert book["has_original"] is False
    assert book["epub_title"] == "雾港夜航"
    assert "缆绳" in await _chapter(admin_client, book["id"])
    # Only the upload response carries the flag.
    response = await admin_client.get(f"/api/books/{book['id']}")
    assert response.json()["zh_simplified"] is False


async def test_traditional_upload_is_not_reported(admin_client, library_id):
    book = await _upload(admin_client, library_id, TRADITIONAL_EPUB)
    assert book["zh_simplified"] is False


async def test_conversion_carries_highlights_along(admin_client, library_id):
    book = await _upload(admin_client, library_id, SIMPLIFIED_EPUB)
    book_id = book["id"]
    # A highlight that starts halfway into 头发 and ends inside 视频.
    response = await admin_client.post(
        f"/api/books/{book_id}/highlights",
        json={
            "cfi_range": "epubcfi(/6/4!/4/4,/1:4,/1:13)",
            "text": "发，用U盘拷了视",
            "prefix": "他剪了头",
            "suffix": "频。缆绳解开的时候",
            "section_index": 1,
            "note": "头发这段",
        },
    )
    assert response.status_code in (200, 201), response.text
    highlight_id = response.json()["id"]

    response = await admin_client.get(f"/api/books/{book_id}/zh-conversion")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["highlights"] == 1
    # The sample is the sentence the phrase option changes too.
    segments = preview["segments"]
    assert "".join(s["before"] for s in segments) == "他剪了头发，用U盘拷了视频。"
    assert "".join(s["phrases"] for s in segments) == "他剪了頭髮，用隨身碟拷了影片。"

    response = await admin_client.post(
        f"/api/books/{book_id}/zh-conversion", json={"mode": "s2twp"}
    )
    assert response.status_code == 200, response.text
    converted = response.json()
    assert converted["epub_language"] == "zh-TW"
    assert converted["has_original"] is True

    chapter = await _chapter(admin_client, book_id)
    assert "他剪了頭髮，用隨身碟拷了影片。" in chapter
    highlights = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    (highlight,) = [h for h in highlights if h["id"] == highlight_id]
    assert highlight["text"] == "髮，用隨身碟拷了影"
    assert highlight["text"] in chapter
    assert highlight["prefix"].endswith("他剪了頭")
    assert highlight["suffix"].startswith("片。纜繩")
    assert highlight["note"] == "头发这段"  # the reader's own words stay

    # The upload is kept as it was; a book already Traditional is left be.
    response = await admin_client.get(f"/api/books/{book_id}/original")
    assert response.content == SIMPLIFIED_EPUB
    response = await admin_client.get(f"/api/books/{book_id}/zh-conversion")
    assert response.json()["segments"] is None
    response = await admin_client.post(
        f"/api/books/{book_id}/zh-conversion", json={"mode": "s2twp"}
    )
    assert response.json()["file_size"] == converted["file_size"]


async def test_character_conversion_can_be_followed_by_phrases(
    admin_client, library_id
):
    book = await _upload(admin_client, library_id, SIMPLIFIED_EPUB)
    await admin_client.post(
        f"/api/books/{book['id']}/zh-conversion", json={"mode": "s2tw"}
    )
    assert "軟件工程師" in await _chapter(admin_client, book["id"])
    await admin_client.post(
        f"/api/books/{book['id']}/zh-conversion", json={"mode": "s2twp"}
    )
    assert "軟體工程師" in await _chapter(admin_client, book["id"])
    # The kept copy is still the upload, not the first conversion.
    response = await admin_client.get(f"/api/books/{book['id']}/original")
    assert response.content == SIMPLIFIED_EPUB


async def test_upload_language_is_read_from_the_text(admin_client, library_id):
    epub = build_epub(
        title="潮汐鐘樓手記",
        language="en",
        chapters=[("第一章", ["退潮之後，沙灘上留著昨夜的腳印與鐘聲。" * 20])],
    )
    book = await _upload(admin_client, library_id, epub)
    assert book["epub_language"] == "zh-TW"
