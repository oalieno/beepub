"""A series is one series however its name is padded.

The key is ``books.series_key`` (migration 068). Before it, SQL trimmed
only ASCII spaces and Python trimmed the full-width one too, so a name
stored with a full-width space at either end was one series when rated
and another when its books were looked up.
"""

import uuid

import pytest
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.book import Book
from app.services.series import series_key_of
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration

# As files carry them: plain, padded with full-width spaces, in another
# case with ASCII padding.
NAMES = ["Night Diner 食堂", "　Night Diner 食堂　", "  night diner 食堂\t"]


async def test_padding_and_case_do_not_split_a_series(admin_client):
    library_id = await create_library(admin_client)
    ids = []
    for n, name in enumerate(NAMES, start=1):
        book = await upload_epub(admin_client, library_id, title=f"第{n}夜")
        ids.append(uuid.UUID(book["id"]))
        # Straight into the row: this is about names already stored.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Book).where(Book.id == ids[-1]).values(epub_series=name)
            )
            await db.commit()

    # The column and the Python helper agree, for every spelling.
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Book.epub_series, Book.series_key).where(Book.id.in_(ids))
            )
        ).all()
    assert {key for _, key in rows} == {"night diner 食堂"}
    assert all(series_key_of(None, name) == key for name, key in rows)

    # One series of three in the grouped list…
    grouped = (
        await admin_client.get("/api/books/grouped", params={"library": library_id})
    ).json()
    assert [(i["type"], i["series"]["book_count"]) for i in grouped["items"]] == [
        ("series", 3)
    ]

    # …and what is said about it under one spelling is found under another.
    response = await admin_client.put(
        "/api/series/rating",
        json={"series_name": NAMES[1], "library_id": library_id, "rating": 4.5},
    )
    assert response.status_code in (200, 204), response.text
    detail = await admin_client.get(
        "/api/series/detail", params={"name": NAMES[0], "library": library_id}
    )
    assert detail.status_code == 200, detail.text
    assert (detail.json()["book_count"], detail.json()["rating"]) == (3, 4.5)


async def test_a_blank_series_is_no_series(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id, title="無題")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Book)
            .where(Book.id == uuid.UUID(book["id"]))
            .values(epub_series="　 ")
        )
        await db.commit()
    grouped = (
        await admin_client.get("/api/books/grouped", params={"library": library_id})
    ).json()
    assert [i["type"] for i in grouped["items"]] == ["book"]
