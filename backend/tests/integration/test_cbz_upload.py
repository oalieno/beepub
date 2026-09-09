"""CBZ upload: packed into a pre-paginated EPUB at ingest, classified an
image book on the spot, source kept for download, pages served in order."""

import zipfile
from io import BytesIO

import pytest

from tests.factories.cbz import LANDSCAPE, PORTRAIT, build_cbz, comic_info_xml
from tests.integration.util import create_library

MANGA = build_cbz(
    [PORTRAIT, PORTRAIT, LANDSCAPE, PORTRAIT],
    comic_info=comic_info_xml(
        title="月台小提琴手 第1話",
        series="月台小提琴手",
        number="1",
        writer="周霜",
        manga="YesAndRightToLeft",
    ),
)


@pytest.fixture
async def library_id(admin_client) -> str:
    return await create_library(admin_client)


async def upload(client, library_id: str, data: bytes, name: str):
    return await client.post(
        "/api/books",
        files={"file": (name, data, "application/vnd.comicbook+zip")},
        data={"library_id": library_id},
    )


async def test_cbz_becomes_an_image_book_with_pages(admin_client, library_id):
    response = await upload(admin_client, library_id, MANGA, "violin.cbz")
    assert response.status_code == 201, response.text
    book = response.json()
    assert book["format"] == "cbz"
    assert book["epub_title"] == "月台小提琴手 第1話"
    assert book["epub_authors"] == ["周霜"]
    assert book["epub_series"] == "月台小提琴手"
    assert book["is_image_book"] is True
    assert book["cover_path"] is not None

    response = await admin_client.get(f"/api/books/{book['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        opf = zf.read("OEBPS/content.opf").decode()
    assert "pre-paginated" in opf

    response = await admin_client.get(f"/api/books/{book['id']}/pages")
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["layout"] == "pre-paginated"
    assert manifest["direction"] == "rtl"
    assert [p["image"] for p in manifest["pages"]] == [
        f"OEBPS/images/{i:04d}.jpg" for i in range(1, 5)
    ]
    assert (manifest["pages"][2]["width"], manifest["pages"][2]["height"]) == LANDSCAPE
    etag = response.headers["etag"]
    response = await admin_client.get(
        f"/api/books/{book['id']}/pages", headers={"If-None-Match": etag}
    )
    assert response.status_code == 304

    # The page images stream through the same content route the reader uses.
    response = await admin_client.get(
        f"/api/books/{book['id']}/content/{manifest['pages'][0]['image']}"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"

    response = await admin_client.get(f"/api/books/{book['id']}/original")
    assert response.status_code == 200
    assert response.content == MANGA
    assert response.headers["content-disposition"].endswith(".cbz")

    # Not a TXT: no zh conversion offered.
    response = await admin_client.post(
        f"/api/books/{book['id']}/zh-conversion", json={"mode": "s2tw"}
    )
    assert response.status_code == 409


async def test_a_text_epub_reports_a_reflowable_manifest(admin_client, library_id):
    from tests.factories.epub import build_epub

    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.epub", build_epub(), "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201
    response = await admin_client.get(f"/api/books/{response.json()['id']}/pages")
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["layout"] == "reflowable"
    assert all(p["image"] is None for p in manifest["pages"])


async def test_bad_cbz_uploads_are_rejected(admin_client, library_id):
    response = await upload(admin_client, library_id, b"not a zip", "junk.cbz")
    assert response.status_code == 400
    assert response.json()["detail"] == "Not a CBZ file"

    response = await upload(
        admin_client, library_id, build_cbz(0, extra={"a.txt": b"x"}), "empty.cbz"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The archive has no images"

    response = await upload(admin_client, library_id, b"x", "comic.cbr")
    assert response.status_code == 400
    assert "CBZ" in response.json()["detail"]

    response = await admin_client.get("/api/books/all")
    assert response.json()["total"] == 0
