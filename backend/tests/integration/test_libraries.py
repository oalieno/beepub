"""Library membership rules — the every-book-in-a-library invariant, for real."""

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


async def test_rename_library(admin_client):
    library_id = await create_library(admin_client, "Old Name")
    response = await admin_client.put(
        f"/api/libraries/{library_id}", json={"name": "New Name"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


async def test_move_book_between_libraries(admin_client):
    lib_a = await create_library(admin_client, "A")
    lib_b = await create_library(admin_client, "B")
    book = await upload_epub(admin_client, lib_a)

    moved = await admin_client.put(
        f"/api/books/{book['id']}/library", json={"library_id": lib_b}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "moved"

    source = (await admin_client.get(f"/api/libraries/{lib_a}/books")).json()
    assert source["items"] == []
    target = (await admin_client.get(f"/api/libraries/{lib_b}/books")).json()
    assert [b["id"] for b in target["items"]] == [book["id"]]
    assert (await admin_client.get(f"/api/books/{book['id']}")).status_code == 200


async def test_move_to_current_library_is_a_noop(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    response = await admin_client.put(
        f"/api/books/{book['id']}/library", json={"library_id": library_id}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unchanged"


async def test_move_validates_book_and_library(admin_client, user_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    response = await admin_client.put(
        "/api/books/00000000-0000-4000-8000-000000000000/library",
        json={"library_id": library_id},
    )
    assert response.status_code == 404

    response = await admin_client.put(
        f"/api/books/{book['id']}/library",
        json={"library_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert response.status_code == 404

    # Admin-only.
    response = await user_client.put(
        f"/api/books/{book['id']}/library", json={"library_id": library_id}
    )
    assert response.status_code == 403


async def test_delete_library_deletes_its_books(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    response = await admin_client.delete(f"/api/libraries/{library_id}")
    assert response.status_code == 204

    assert (await admin_client.get(f"/api/books/{book['id']}")).status_code == 404
    listing = (await admin_client.get("/api/books/all")).json()
    assert listing["total"] == 0
