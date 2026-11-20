"""Beside each cover, a small one for the lists."""

import io
import os

from PIL import Image
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.book import Book
from app.services.storage import (
    THUMBNAIL_WIDTH,
    cover_thumbnail_path,
    make_missing_thumbnails,
)
from tests.integration.util import create_library, upload_epub


async def _cover_path(book_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(Book.cover_path).where(Book.id == book_id))
        ).scalar_one()


async def test_a_cover_is_saved_with_its_thumbnail_and_deleted_with_it(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    cover = await _cover_path(book["id"])
    thumbnail = cover_thumbnail_path(cover)
    assert os.path.exists(thumbnail)
    with Image.open(thumbnail) as img:
        assert img.format == "WEBP"
        assert img.width <= THUMBNAIL_WIDTH

    # Asked for through the API (the app's way to a cover).
    response = await admin_client.get(
        f"/api/books/{book['id']}/cover", params={"size": "thumb"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    response = await admin_client.get(f"/api/books/{book['id']}/cover")
    assert response.headers["content-type"] == "image/jpeg"

    response = await admin_client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 204, response.text
    assert not os.path.exists(cover)
    assert not os.path.exists(thumbnail)


async def test_a_replaced_cover_has_a_new_thumbnail(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    thumbnail = cover_thumbnail_path(await _cover_path(book["id"]))
    with Image.open(thumbnail) as img:
        before = img.convert("RGB").getpixel((0, 0))

    picture = io.BytesIO()
    Image.new("RGB", (1200, 1800), (200, 30, 30)).save(picture, "PNG")
    response = await admin_client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("cover.png", picture.getvalue(), "image/png")},
    )
    assert response.status_code == 200, response.text
    with Image.open(thumbnail) as img:
        assert img.width == THUMBNAIL_WIDTH
        after = img.convert("RGB").getpixel((0, 0))
    assert after != before
    assert abs(after[0] - 200) < 12 and after[1] < 60


async def test_a_book_without_a_thumbnail_answers_with_its_cover(admin_client):
    """Covers stored before thumbnails were made have none until the
    worker's walk (or the script) has made them."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    cover = await _cover_path(book["id"])
    os.remove(cover_thumbnail_path(cover))

    response = await admin_client.get(
        f"/api/books/{book['id']}/cover", params={"size": "thumb"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"

    # The walk makes the missing one, and only that.
    covers = os.path.dirname(cover)
    _seen, made, failed = make_missing_thumbnails(covers)
    assert made >= 1 and failed == 0
    assert os.path.exists(cover_thumbnail_path(cover))
    assert make_missing_thumbnails(covers)[1:] == (0, 0)
    response = await admin_client.get(
        f"/api/books/{book['id']}/cover", params={"size": "thumb"}
    )
    assert response.headers["content-type"] == "image/webp"
