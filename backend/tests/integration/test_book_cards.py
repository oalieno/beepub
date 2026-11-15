"""The same book shows the same card in every list."""

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration

ABOUT_THE_READER = (
    "reading_status",
    "is_favorite",
    "user_rating",
    "reading_percentage",
    "edition_count",
)


async def test_a_book_reads_the_same_in_every_list(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id, title="潮間帶觀察筆記")
    book_id = book["id"]

    for path, body in (
        ("rating", {"rating": 4.5}),
        ("favorite", {"is_favorite": True}),
        ("reading-status", {"reading_status": "currently_reading"}),
        (
            "progress",
            {
                "cfi": "epubcfi(/6/4!/4/2/1:42)",
                "percentage": 37.5,
                "font_size": 18,
                "section_index": 1,
                "section_page": 3,
            },
        ),
    ):
        response = await admin_client.put(f"/api/books/{book_id}/{path}", json=body)
        assert response.status_code in (200, 204), (path, response.text)

    listed = (await admin_client.get("/api/books")).json()["items"]
    grouped = (await admin_client.get("/api/books/grouped")).json()["items"]
    mine = (await admin_client.get("/api/books/me")).json()["items"]

    cards = {
        "list": next(b for b in listed if b["id"] == book_id),
        "grouped": next(
            g["book"] for g in grouped if g["book"] and g["book"]["id"] == book_id
        ),
        "mine": next(b for b in mine if b["id"] == book_id),
    }
    expected = {
        "reading_status": "currently_reading",
        "is_favorite": True,
        "user_rating": 4.5,
        "reading_percentage": 37.5,
        "edition_count": None,
    }
    for where, card in cards.items():
        assert {k: card[k] for k in ABOUT_THE_READER} == expected, where
