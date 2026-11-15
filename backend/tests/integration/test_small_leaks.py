"""Things a user could learn that were not theirs to learn."""

import uuid

import pytest

from app.database import AsyncSessionLocal
from app.models.tag import BookTag, TagCategory, TagSource
from tests.integration.conftest import ADMIN_CREDENTIALS, USER_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


async def _user_id(admin_client, username: str) -> str:
    users = (await admin_client.get("/api/admin/users")).json()
    return next(u["id"] for u in users if u["username"] == username)


async def test_closed_registration_does_not_say_which_names_exist(admin_client, client):
    # (Registration is closed unless the admin opens it.)
    taken = await client.post(
        "/api/auth/register",
        json={"username": ADMIN_CREDENTIALS["username"], "password": "x" * 12},
    )
    free = await client.post(
        "/api/auth/register",
        json={"username": "nobody-by-this-name", "password": "x" * 12},
    )
    assert taken.status_code == free.status_code == 403
    assert taken.json() == free.json()
    assert taken.json()["code"] == "registration_closed"


async def test_a_reader_sees_who_reported_only_for_their_own(admin_client, user_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    path = f"/api/books/{book['id']}/reports"
    for reporter in (admin_client, user_client):
        response = await reporter.post(path, json={"issue_type": "cant_open"})
        assert response.status_code == 201, response.text
    admin_id = await _user_id(admin_client, ADMIN_CREDENTIALS["username"])
    reader_id = await _user_id(admin_client, USER_CREDENTIALS["username"])

    seen_by_reader = (await user_client.get(path)).json()
    assert sorted(r["reported_by"] or "" for r in seen_by_reader) == ["", reader_id]

    seen_by_admin = (await admin_client.get(path)).json()
    assert sorted(r["reported_by"] for r in seen_by_admin) == sorted(
        [admin_id, reader_id]
    )


async def test_tag_counts_leave_out_libraries_the_user_is_kept_from(
    admin_client, user_client
):
    lib_open = await create_library(admin_client, "Open")
    lib_closed = await create_library(admin_client, "Closed")
    books = [
        await upload_epub(admin_client, lib_open, title="Open One"),
        await upload_epub(admin_client, lib_closed, title="Closed One"),
        await upload_epub(admin_client, lib_closed, title="Closed Two"),
    ]
    async with AsyncSessionLocal() as db:
        for book in books:
            db.add(
                BookTag(
                    book_id=uuid.UUID(book["id"]),
                    tag="mystery",
                    category=TagCategory.genre,
                    source=TagSource.manual,
                    confidence=1.0,
                )
            )
        await db.commit()

    async def mystery_count(c) -> int:
        tags = (await c.get("/api/tags")).json()
        return next((t["book_count"] for t in tags if t["tag"] == "mystery"), 0)

    assert await mystery_count(user_client) == 3  # (no exclusion yet)

    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    response = await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": [lib_closed]},
    )
    assert response.status_code == 200, response.text

    assert await mystery_count(user_client) == 1
    assert await mystery_count(admin_client) == 3
