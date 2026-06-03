"""Tests for PUT /api/auth/tier-theme — per-user tier-list theme."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.deps import get_current_user
from app.main import app
from app.models.user import User, UserRole


def _make_user() -> User:
    user = User(
        id=uuid.uuid4(),
        username="reader",
        password_hash="hashed",
        role=UserRole.user,
        is_active=True,
        can_download=False,
    )
    user.created_at = datetime.now(UTC)
    user.tier_theme = None
    return user


def _mock_db() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def user():
    return _make_user()


def _override(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: _mock_db()


class TestUpdateTierTheme:
    @pytest.mark.asyncio
    async def test_set_valid_theme(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/auth/tier-theme",
                    json={
                        "tier_theme": [
                            {"min": 4.5, "label": "UR", "color": "#f00"},
                            {"min": 0.5, "label": "N", "color": "#00f"},
                        ]
                    },
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["tier_theme"][0]["label"] == "UR"
            assert user.tier_theme[0]["min"] == 4.5
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_reset_theme_with_null(self, user):
        user.tier_theme = [{"min": 5, "label": "S", "color": "#f00"}]
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/auth/tier-theme", json={"tier_theme": None}
                )
            assert resp.status_code == 200
            assert resp.json()["tier_theme"] is None
            assert user.tier_theme is None
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_rejects_empty_theme(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put("/api/auth/tier-theme", json={"tier_theme": []})
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_rejects_band_min_out_of_range(self, user):
        _override(user)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/auth/tier-theme",
                    json={"tier_theme": [{"min": 9, "label": "X", "color": "#f00"}]},
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put("/api/auth/tier-theme", json={"tier_theme": None})
        assert resp.status_code in (401, 403, 307)
