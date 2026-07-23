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


async def test_recap_shows_only_read_chapters(admin_client, user_client, library_id):
    """The recap endpoint returns stored chapter summaries strictly
    before the reader's spine position, never at or past it, and fails
    closed without a parseable position."""
    import uuid as _uuid

    from app.database import engine
    from app.models.book_text import BookTextChunk

    book = await upload(admin_client, library_id, build_epub())
    book_id = book["id"]

    filler = "字" * 1200  # past the non-content length filter
    async with engine.begin() as conn:
        for spine, (title, summary) in enumerate(
            [
                ("版權頁", None),  # never summarized
                ("序", "*   Task: Summarize the provided text."),  # LLM echo
                ("第一章", "主角出場。"),
                ("第二章", "衝突爆發。"),
                ("第三章", "尚未讀到的雷。"),
            ]
        ):
            await conn.execute(
                BookTextChunk.__table__.insert().values(
                    id=_uuid.uuid4(),
                    book_id=book_id,
                    spine_index=spine,
                    section_title=title,
                    text=filler,
                    char_offset=0,
                    summary=summary,
                )
            )

    # Reading in spine 3 (cfi /6/8 → index 3): only chapter 1 shows —
    # the echo row is filtered, chapter 2 is in progress, chapter 3 is
    # the future.
    resp = await admin_client.get(f"/api/books/{book_id}/recap?cfi=epubcfi(/6/8!/4/2)")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_any"] is True
    assert [s["title"] for s in data["sections"]] == ["第一章"]

    # No position → no sections (fail closed), but has_any still reports.
    resp = await admin_client.get(f"/api/books/{book_id}/recap")
    assert resp.json() == {"sections": [], "has_any": True}

    # Access control rides _get_book_with_access: a user excluded from
    # the library can't read summaries.
    users = (await admin_client.get("/api/admin/users")).json()
    user_id = next(u["id"] for u in users if u["role"] != "admin")
    resp = await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": [library_id]},
    )
    assert resp.status_code == 200
    resp = await user_client.get(f"/api/books/{book_id}/recap?cfi=epubcfi(/6/8!/4/2)")
    assert resp.status_code == 403
