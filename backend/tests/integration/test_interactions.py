"""Per-user book state: ratings, favorites, progress, highlights, status."""

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


@pytest.fixture
async def book_id(admin_client) -> str:
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    return book["id"]


async def test_rating_roundtrip_and_validation(admin_client, book_id):
    response = await admin_client.put(
        f"/api/books/{book_id}/rating", json={"rating": 4.5}
    )
    assert response.status_code == 200

    interaction = (await admin_client.get(f"/api/books/{book_id}/interaction")).json()
    assert interaction["rating"] == 4.5

    response = await admin_client.put(
        f"/api/books/{book_id}/rating", json={"rating": 4.3}
    )
    assert response.status_code == 400

    # Clearing the rating is allowed.
    response = await admin_client.put(
        f"/api/books/{book_id}/rating", json={"rating": None}
    )
    assert response.status_code == 200


async def test_favorite_toggle(admin_client, book_id):
    await admin_client.put(f"/api/books/{book_id}/favorite", json={"is_favorite": True})
    interaction = (await admin_client.get(f"/api/books/{book_id}/interaction")).json()
    assert interaction["is_favorite"] is True

    await admin_client.put(
        f"/api/books/{book_id}/favorite", json={"is_favorite": False}
    )
    interaction = (await admin_client.get(f"/api/books/{book_id}/interaction")).json()
    assert interaction["is_favorite"] is False


async def test_reading_progress_roundtrip(admin_client, book_id):
    payload = {
        "cfi": "epubcfi(/6/4[chapter1]!/4/2/1:42)",
        "percentage": 37.5,
        "font_size": 18,
        "section_index": 1,
        "section_page": 3,
    }
    response = await admin_client.put(f"/api/books/{book_id}/progress", json=payload)
    assert response.status_code == 200, response.text

    progress = (await admin_client.get(f"/api/books/{book_id}/progress")).json()
    assert progress["cfi"] == payload["cfi"]
    assert progress["percentage"] == 37.5
    assert progress["font_size"] == 18


async def test_highlight_lifecycle(admin_client, book_id):
    created = await admin_client.post(
        f"/api/books/{book_id}/highlights",
        json={
            "cfi_range": "epubcfi(/6/4!/4/2,/1:0,/1:20)",
            "text": "The quick brown fox",
            "color": "yellow",
        },
    )
    assert created.status_code == 201, created.text
    highlight_id = created.json()["id"]

    listing = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    assert [h["id"] for h in listing] == [highlight_id]

    updated = await admin_client.put(
        f"/api/books/{book_id}/highlights/{highlight_id}",
        json={"color": "blue", "note": "important"},
    )
    assert updated.status_code == 200
    assert updated.json()["color"] == "blue"
    assert updated.json()["note"] == "important"

    deleted = await admin_client.delete(
        f"/api/books/{book_id}/highlights/{highlight_id}"
    )
    assert deleted.status_code == 204

    listing = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    assert listing == []


async def test_interactions_are_per_user(admin_client, user_client, book_id):
    await admin_client.put(f"/api/books/{book_id}/rating", json={"rating": 5})

    interaction = (await user_client.get(f"/api/books/{book_id}/interaction")).json()
    assert interaction["rating"] is None


async def test_reading_status(admin_client, book_id):
    response = await admin_client.put(
        f"/api/books/{book_id}/reading-status", json={"reading_status": "read"}
    )
    assert response.status_code == 200, response.text
    interaction = (await admin_client.get(f"/api/books/{book_id}/interaction")).json()
    assert interaction["reading_status"] == "read"
