"""Bookshelf CRUD and membership through the real API."""

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


async def test_shelf_lifecycle(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    created = await admin_client.post("/api/bookshelves", json={"name": "Favorites"})
    assert created.status_code == 201, created.text
    shelf_id = created.json()["id"]

    added = await admin_client.post(
        f"/api/bookshelves/{shelf_id}/books", json={"book_id": book["id"]}
    )
    assert added.status_code == 201, added.text

    # Adding twice is a client error, not a duplicate row.
    duplicate = await admin_client.post(
        f"/api/bookshelves/{shelf_id}/books", json={"book_id": book["id"]}
    )
    assert duplicate.status_code == 409

    items = (await admin_client.get(f"/api/bookshelves/{shelf_id}/items")).json()
    assert len(items) == 1

    removed = await admin_client.delete(
        f"/api/bookshelves/{shelf_id}/books/{book['id']}"
    )
    assert removed.status_code == 204
    items = (await admin_client.get(f"/api/bookshelves/{shelf_id}/items")).json()
    assert items == []

    deleted = await admin_client.delete(f"/api/bookshelves/{shelf_id}")
    assert deleted.status_code == 204
    assert (await admin_client.get(f"/api/bookshelves/{shelf_id}")).status_code == 404


async def test_shelves_are_private_to_their_owner(admin_client, user_client):
    created = await admin_client.post("/api/bookshelves", json={"name": "Admin only"})
    shelf_id = created.json()["id"]

    response = await user_client.get(f"/api/bookshelves/{shelf_id}")
    assert response.status_code == 404

    listing = (await user_client.get("/api/bookshelves")).json()
    assert listing == []
