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

    listing = (await user_client.get("/api/books")).json()
    assert [b["epub_title"] for b in listing["items"]] == ["Public Book"]

    # Direct object access must be blocked too, not just the listings.
    response = await user_client.get(f"/api/books/{hidden['id']}")
    assert response.status_code == 403

    # The admin still sees everything.
    listing = (await admin_client.get("/api/books")).json()
    assert listing["total"] == 2

    # Lifting the exclusion restores visibility.
    await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": []},
    )
    response = await user_client.get(f"/api/books/{hidden['id']}")
    assert response.status_code == 200


async def test_book_lists_refuse_an_excluded_library(admin_client, user_client):
    """Asking either list for one library by id is refused outright when the
    user is excluded from it — the grouped list applies no exclusion filter
    of its own once it is scoped to a library."""
    lib_open = await create_library(admin_client, "Lantern Room")
    lib_closed = await create_library(admin_client, "Sealed Annex")
    await upload_epub(
        admin_client,
        lib_open,
        title="The Tin Orchard",
        identifier="urn:uuid:00000000-0000-4000-8000-000000000301",
    )
    await upload_epub(
        admin_client,
        lib_closed,
        title="A Ledger of Moths",
        identifier="urn:uuid:00000000-0000-4000-8000-000000000302",
    )

    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    response = await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": [lib_closed]},
    )
    assert response.status_code == 200, response.text

    for url in ("/api/books", "/api/books/grouped"):
        response = await user_client.get(url, params={"library": lib_closed})
        assert response.status_code == 403, url
        assert response.json()["detail"] == "Access denied", url

        # A library the user may see still answers...
        response = await user_client.get(url, params={"library": lib_open})
        assert response.status_code == 200, url
        assert response.json()["total"] == 1, url

        # ...the unscoped list leaves the excluded library's book out...
        response = await user_client.get(url)
        assert response.status_code == 200, url
        assert response.json()["total"] == 1, url

        # ...and the admin is never excluded.
        response = await admin_client.get(url, params={"library": lib_closed})
        assert response.status_code == 200, url
        assert response.json()["total"] == 1, url


async def test_book_lists_404_for_an_unknown_library(admin_client, user_client):
    library_id = await create_library(admin_client, "Lantern Room")
    await upload_epub(admin_client, library_id, title="The Tin Orchard")

    unknown = "00000000-0000-4000-8000-0000000000ff"
    for client in (admin_client, user_client):
        for url in ("/api/books", "/api/books/grouped"):
            response = await client.get(url, params={"library": unknown})
            assert response.status_code == 404, url
            assert response.json()["detail"] == "Library not found", url


async def test_library_scoped_list_carries_user_rating(admin_client):
    """One library's flat list carries the user's own rating, as the
    all-libraries list does."""
    library_id = await create_library(admin_client, "Lantern Room")
    rated = await upload_epub(
        admin_client,
        library_id,
        title="The Tin Orchard",
        identifier="urn:uuid:00000000-0000-4000-8000-000000000301",
    )
    unrated = await upload_epub(
        admin_client,
        library_id,
        title="A Ledger of Moths",
        identifier="urn:uuid:00000000-0000-4000-8000-000000000302",
    )
    response = await admin_client.put(
        f"/api/books/{rated['id']}/rating", json={"rating": 4.5}
    )
    assert response.status_code == 200, response.text

    response = await admin_client.get("/api/books", params={"library": library_id})
    assert response.status_code == 200, response.text
    by_id = {item["id"]: item for item in response.json()["items"]}
    assert by_id[rated["id"]]["user_rating"] == 4.5
    assert by_id[unrated["id"]]["user_rating"] is None
