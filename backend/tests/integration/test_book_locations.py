"""Shared cache of epub.js reading locations."""

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


@pytest.fixture
async def book_id(admin_client) -> str:
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    return book["id"]


LOCATIONS = '["epubcfi(/6/2!/4/2/1:0)","epubcfi(/6/4!/4/8/1:120)"]'


async def test_locations_roundtrip(admin_client, book_id):
    # Nobody has generated them yet.
    response = await admin_client.get(f"/api/books/{book_id}/locations")
    assert response.status_code == 204

    saved = await admin_client.put(
        f"/api/books/{book_id}/locations",
        json={"fingerprint": "urn:uuid:x:12:1600", "locations": LOCATIONS},
    )
    assert saved.status_code == 200

    response = await admin_client.get(f"/api/books/{book_id}/locations")
    assert response.status_code == 200
    body = response.json()
    assert body["fingerprint"] == "urn:uuid:x:12:1600"
    assert body["locations"] == LOCATIONS


async def test_locations_upsert_overwrites(admin_client, book_id):
    for fp in ("fp:1", "fp:2"):
        saved = await admin_client.put(
            f"/api/books/{book_id}/locations",
            json={"fingerprint": fp, "locations": LOCATIONS},
        )
        assert saved.status_code == 200

    body = (await admin_client.get(f"/api/books/{book_id}/locations")).json()
    assert body["fingerprint"] == "fp:2"


async def test_locations_rejects_non_array(admin_client, book_id):
    response = await admin_client.put(
        f"/api/books/{book_id}/locations",
        json={"fingerprint": "fp", "locations": '{"not": "an array"}'},
    )
    assert response.status_code == 422


async def test_locations_readable_by_any_user_with_access(
    admin_client, user_client, book_id
):
    await admin_client.put(
        f"/api/books/{book_id}/locations",
        json={"fingerprint": "fp", "locations": LOCATIONS},
    )
    # A normal user with library access downloads what the admin generated.
    response = await user_client.get(f"/api/books/{book_id}/locations")
    assert response.status_code == 200
    assert response.json()["locations"] == LOCATIONS
