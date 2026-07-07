"""Every book must belong to at least one library.

Outside of a library a book is unreachable by every listing (all/feed/
search/random), even for admins — so uploads require a library and the
last library membership cannot be removed. Also covers the empty-gacha
case: /books/random returns an empty list, not an error.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.main import app
from app.models.user import User, UserRole


def _make_admin() -> User:
    return User(
        id=uuid.uuid4(),
        username="admin",
        password_hash="hashed",
        role=UserRole.admin,
        is_active=True,
        can_download=True,
        can_upload=True,
    )


def _override(user: User, session) -> None:
    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user


def _cleanup() -> None:
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestRandomBooksEmpty:
    @pytest.mark.asyncio
    async def test_no_books_returns_empty_list_not_error(self):
        session = AsyncMock()
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=empty)
        _override(_make_admin(), session)
        try:
            async with _client() as client:
                resp = await client.get("/api/books/random")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            _cleanup()


class TestUploadRequiresLibrary:
    @pytest.mark.asyncio
    async def test_upload_without_library_id_is_422(self):
        _override(_make_admin(), AsyncMock())
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/books",
                    files={"file": ("book.epub", b"fake", "application/epub+zip")},
                )
            assert resp.status_code == 422
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_bulk_upload_without_library_id_is_422(self):
        _override(_make_admin(), AsyncMock())
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/books/bulk",
                    files=[("files", ("book.epub", b"fake", "application/epub+zip"))],
                )
            assert resp.status_code == 422
        finally:
            _cleanup()


class TestRemoveLastLibraryMembership:
    @pytest.mark.asyncio
    async def test_removing_only_membership_is_409(self):
        session = AsyncMock()

        membership = MagicMock()
        found = MagicMock()
        found.scalar_one_or_none.return_value = membership

        not_in_work = MagicMock()
        not_in_work.scalar_one_or_none.return_value = None

        one_membership = MagicMock()
        one_membership.scalar.return_value = 1

        session.execute = AsyncMock(side_effect=[found, not_in_work, one_membership])
        _override(_make_admin(), session)
        try:
            async with _client() as client:
                resp = await client.delete(
                    f"/api/libraries/{uuid.uuid4()}/books/{uuid.uuid4()}"
                )
            assert resp.status_code == 409
            assert "only library" in resp.json()["detail"]
            session.delete.assert_not_called()
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_removing_one_of_two_memberships_succeeds(self):
        session = AsyncMock()

        membership = MagicMock()
        found = MagicMock()
        found.scalar_one_or_none.return_value = membership

        not_in_work = MagicMock()
        not_in_work.scalar_one_or_none.return_value = None

        two_memberships = MagicMock()
        two_memberships.scalar.return_value = 2

        session.execute = AsyncMock(side_effect=[found, not_in_work, two_memberships])
        _override(_make_admin(), session)
        try:
            async with _client() as client:
                resp = await client.delete(
                    f"/api/libraries/{uuid.uuid4()}/books/{uuid.uuid4()}"
                )
            assert resp.status_code == 204
            session.delete.assert_called_once_with(membership)
        finally:
            _cleanup()
