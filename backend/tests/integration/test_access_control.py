"""Permission and library-visibility enforcement with real users and books."""

import pytest

from tests.integration.conftest import USER_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


async def _user_id(admin_client, username: str) -> str:
    users = (await admin_client.get("/api/admin/users")).json()
    return next(u["id"] for u in users if u["username"] == username)


async def test_upload_requires_permission(admin_client, user_client):
    library_id = await create_library(admin_client)

    from tests.factories.epub import build_epub

    response = await user_client.post(
        "/api/books",
        files={"file": ("book.epub", build_epub(), "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Upload permission required"

    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    granted = await admin_client.put(
        f"/api/admin/users/{user_id}/permissions", json={"can_upload": True}
    )
    assert granted.status_code == 200

    response = await user_client.post(
        "/api/books",
        files={"file": ("book.epub", build_epub(), "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text


async def test_download_allowed_by_default_and_revocable(admin_client, user_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    # New accounts can download out of the box (OPDS/kosync depend on it).
    response = await user_client.get(f"/api/books/{book['id']}/file")
    assert response.status_code == 200

    # The permission remains as an opt-in restriction.
    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    await admin_client.put(
        f"/api/admin/users/{user_id}/permissions", json={"can_download": False}
    )

    response = await user_client.get(f"/api/books/{book['id']}/file")
    assert response.status_code == 403
    assert response.json()["detail"] == "Download permission required"


async def test_excluded_library_is_invisible(admin_client, user_client):
    lib_a = await create_library(admin_client, "Visible")
    lib_b = await create_library(admin_client, "Hidden")
    await upload_epub(admin_client, lib_a, title="Public Book")
    hidden = await upload_epub(admin_client, lib_b, title="Secret Book")

    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    response = await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": [lib_b]},
    )
    assert response.status_code == 200, response.text

    listing = (await user_client.get("/api/books/all")).json()
    assert [b["epub_title"] for b in listing["items"]] == ["Public Book"]

    # Direct object access must be blocked too, not just the listings.
    response = await user_client.get(f"/api/books/{hidden['id']}")
    assert response.status_code == 403

    # The admin still sees everything.
    listing = (await admin_client.get("/api/books/all")).json()
    assert listing["total"] == 2

    # Lifting the exclusion restores visibility.
    await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": []},
    )
    response = await user_client.get(f"/api/books/{hidden['id']}")
    assert response.status_code == 200
