"""Tests for the /api/series router (mocked DB)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.deps import get_current_user
from app.main import app
from app.models.user import User, UserRole
from app.services.series import normalize_series_name


def _make_user() -> User:
    return User(
        id=uuid.uuid4(),
        username="reader",
        password_hash="hashed",
        role=UserRole.user,
        is_active=True,
        can_download=False,
    )


def _mock_db() -> AsyncMock:
    session = AsyncMock()

    async def fake_execute(stmt, params=None):
        result = MagicMock()
        result.mappings.return_value = []  # list_series iterates this
        result.scalar_one_or_none.return_value = None  # get-or-create -> new row
        result.scalar.return_value = None
        return result

    session.execute = fake_execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def user():
    return _make_user()


def _override(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: _mock_db()


class TestNormalizeSeriesName:
    def test_strips_and_lowercases(self):
        assert normalize_series_name("  Foundation ") == "foundation"

    def test_empty_is_none(self):
        assert normalize_series_name("") is None
        assert normalize_series_name("   ") is None
        assert normalize_series_name(None) is None


class TestSeriesEndpoints:
    @pytest.mark.asyncio
    async def test_list_returns_200(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/series/rated")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_set_rating_valid(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/series/rating",
                    json={"series_name": "Foundation", "rating": 4.5},
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_set_rating_null_clears(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/series/rating",
                    json={"series_name": "Foundation", "rating": None},
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_rejects_non_half_step_rating(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/series/rating",
                    json={"series_name": "Foundation", "rating": 4.3},
                )
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_rejects_blank_series_name(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/series/rating",
                    json={"series_name": "   ", "rating": 4},
                )
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_set_notes(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/series/notes",
                    json={"series_name": "Foundation", "notes": "great"},
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/series/rated")
        assert resp.status_code in (401, 403, 307)

    @pytest.mark.asyncio
    async def test_library_series_paginated(self):
        # Admin user: _get_accessible_library returns after the first lookup.
        admin = User(
            id=uuid.uuid4(),
            username="admin",
            password_hash="hashed",
            role=UserRole.admin,
            is_active=True,
            can_download=False,
        )

        def _admin_db() -> AsyncMock:
            session = AsyncMock()

            async def fake_execute(stmt, params=None):
                result = MagicMock()
                result.scalar_one_or_none.return_value = object()  # library exists
                result.mappings.return_value = []  # no series rows
                return result

            session.execute = fake_execute
            return session

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: _admin_db()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/libraries/{uuid.uuid4()}/series?search=foo&limit=20"
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body == {"items": [], "total": 0}
        finally:
            app.dependency_overrides.clear()
