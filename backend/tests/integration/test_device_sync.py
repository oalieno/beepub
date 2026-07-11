"""Device-sync endpoints: digest lookup for linking local books."""

import pytest

from tests.integration.conftest import USER_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


async def _document_digest(client, book_id: str) -> str:
    """The digest the device computes for the book's file (partial md5)."""
    from sqlalchemy import select

    from app.database import engine
    from app.models.book import Book

    async with engine.connect() as conn:
        result = await conn.execute(select(Book.partial_md5).where(Book.id == book_id))
        return result.scalar_one()


async def _user_id(admin_client, username: str) -> str:
    users = (await admin_client.get("/api/admin/users")).json()
    return next(u["id"] for u in users if u["username"] == username)


async def test_by_digest_matches_accessible_book(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id, title="Linked Book")
    digest = await _document_digest(admin_client, book["id"])

    response = await admin_client.post(
        "/api/books/by-digest",
        json={"digests": [digest, "0" * 32]},
    )
    assert response.status_code == 200
    matches = response.json()["matches"]
    # Known digest resolves; the unknown one is simply absent.
    assert set(matches) == {digest}
    assert matches[digest]["id"] == book["id"]
    assert matches[digest]["title"] == "Linked Book"


async def test_by_digest_empty_request(admin_client):
    response = await admin_client.post("/api/books/by-digest", json={"digests": []})
    assert response.status_code == 200
    assert response.json() == {"matches": {}}


async def test_by_digest_respects_library_exclusion(admin_client, user_client):
    lib = await create_library(admin_client, "Hidden Digest Lib")
    book = await upload_epub(admin_client, lib, title="Hidden Book")
    digest = await _document_digest(admin_client, book["id"])

    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    response = await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": [lib]},
    )
    assert response.status_code == 200, response.text

    matches = (
        await user_client.post("/api/books/by-digest", json={"digests": [digest]})
    ).json()["matches"]
    assert matches == {}

    # Lifting the exclusion restores the match.
    await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": []},
    )
    matches = (
        await user_client.post("/api/books/by-digest", json={"digests": [digest]})
    ).json()["matches"]
    assert matches[digest]["id"] == book["id"]


async def test_by_digest_validates_shape(admin_client):
    # Wrong digest length → 422.
    response = await admin_client.post(
        "/api/books/by-digest", json={"digests": ["abc"]}
    )
    assert response.status_code == 422
    # Oversized batch → 422.
    response = await admin_client.post(
        "/api/books/by-digest", json={"digests": ["a" * 32] * 501}
    )
    assert response.status_code == 422


async def test_by_digest_requires_auth(client):
    response = await client.post(
        "/api/books/by-digest", json={"digests": ["a" * 32]}
    )
    assert response.status_code == 401
