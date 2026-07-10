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


async def test_highlight_anchor_context_roundtrip(admin_client, book_id):
    """prefix/suffix/section_index (re-anchoring raw material) persist when
    given and stay null for clients that don't send them."""
    with_context = await admin_client.post(
        f"/api/books/{book_id}/highlights",
        json={
            "cfi_range": "epubcfi(/6/4!/4/2,/1:10,/1:29)",
            "text": "The quick brown fox",
            "color": "yellow",
            "prefix": "Once upon a time, ",
            "suffix": " jumped over the lazy dog.",
            "section_index": 1,
        },
    )
    assert with_context.status_code == 201, with_context.text
    body = with_context.json()
    assert body["prefix"] == "Once upon a time, "
    assert body["suffix"] == " jumped over the lazy dog."
    assert body["section_index"] == 1

    without_context = await admin_client.post(
        f"/api/books/{book_id}/highlights",
        json={
            "cfi_range": "epubcfi(/6/4!/4/2,/1:0,/1:9)",
            "text": "The quick",
            "color": "blue",
        },
    )
    assert without_context.status_code == 201, without_context.text
    assert without_context.json()["prefix"] is None
    assert without_context.json()["suffix"] is None
    assert without_context.json()["section_index"] is None

    listing = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    by_id = {h["id"]: h for h in listing}
    assert by_id[body["id"]]["section_index"] == 1

    # Healing: a client that re-anchored the quote writes the new position
    # back without touching color/note.
    healed = await admin_client.put(
        f"/api/books/{book_id}/highlights/{body['id']}",
        json={"cfi_range": "epubcfi(/6/6!/4/4,/1:2,/1:21)", "section_index": 2},
    )
    assert healed.status_code == 200, healed.text
    assert healed.json()["cfi_range"] == "epubcfi(/6/6!/4/4,/1:2,/1:21)"
    assert healed.json()["section_index"] == 2
    assert healed.json()["color"] == "yellow"
    assert healed.json()["prefix"] == "Once upon a time, "

    for h in listing:
        await admin_client.delete(f"/api/books/{book_id}/highlights/{h['id']}")


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
