"""Cross-book highlights list (GET /api/highlights): pagination, tombstone
filtering, per-user scoping."""

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


@pytest.fixture
async def book_id(admin_client) -> str:
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    return book["id"]


async def _create_highlight(client, book_id: str, text: str) -> str:
    response = await client.post(
        f"/api/books/{book_id}/highlights",
        json={
            "cfi_range": "epubcfi(/6/4!/4/2,/1:0,/1:20)",
            "text": text,
            "color": "yellow",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_global_highlights_pagination_and_tombstones(admin_client, book_id):
    ids = [
        await _create_highlight(admin_client, book_id, f"highlight {i}")
        for i in range(3)
    ]
    deleted = await admin_client.delete(f"/api/books/{book_id}/highlights/{ids[0]}")
    assert deleted.status_code == 204

    body = (await admin_client.get("/api/highlights")).json()
    assert body["total"] == 2
    listed_ids = [h["id"] for h in body["items"]]
    assert ids[0] not in listed_ids
    assert set(listed_ids) == {ids[1], ids[2]}
    # Newest first.
    created = [h["created_at"] for h in body["items"]]
    assert created == sorted(created, reverse=True)

    page = (await admin_client.get("/api/highlights?limit=1&offset=1")).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1


async def test_global_highlights_scoped_to_user(admin_client, user_client, book_id):
    await _create_highlight(admin_client, book_id, "admin's highlight")

    body = (await user_client.get("/api/highlights")).json()
    assert body["total"] == 0
    assert body["items"] == []
