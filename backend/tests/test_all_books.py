"""Tests for the GET /api/books/all endpoint — schema and query parameter validation."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.deps import get_current_user
from app.main import app
from app.models.user import User, UserRole
from app.schemas.book import PaginatedBooks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin() -> User:
    user = User(
        id=uuid.uuid4(),
        username="admin",
        password_hash="hashed",
        role=UserRole.admin,
        is_active=True,
    )
    return user


def _make_user() -> User:
    user = User(
        id=uuid.uuid4(),
        username="reader",
        password_hash="hashed",
        role=UserRole.user,
        is_active=True,
    )
    return user


def _mock_db_returning(items: list, total: int):
    """Mock DB session that returns items for the query and total for count."""
    session = AsyncMock()

    async def fake_execute(stmt):
        result = MagicMock()
        stmt_str = ""
        try:
            compiled = stmt.compile()
            stmt_str = str(compiled).lower()
        except Exception:
            pass

        if "count" in stmt_str:
            result.scalar.return_value = total
        else:
            result.scalars.return_value = MagicMock(all=MagicMock(return_value=items))
        return result

    session.execute = fake_execute
    return session


# ---------------------------------------------------------------------------
# PaginatedBooks schema
# ---------------------------------------------------------------------------


class TestPaginatedBooksSchema:
    def test_empty_result(self):
        result = PaginatedBooks(items=[], total=0)
        assert result.items == []
        assert result.total == 0

    def test_with_items(self):
        result = PaginatedBooks(items=[], total=42)
        assert result.total == 42

    def test_serialization(self):
        result = PaginatedBooks(items=[], total=5)
        data = result.model_dump()
        assert data["total"] == 5
        assert data["items"] == []


# ---------------------------------------------------------------------------
# Endpoint integration tests (mocked DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user():
    return _make_admin()


@pytest.fixture
def regular_user():
    return _make_user()


class TestListAllBooksEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200_for_admin(self, admin_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/books/all")
            assert resp.status_code == 200
            data = resp.json()
            assert "items" in data
            assert "total" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_returns_200_for_regular_user(self, regular_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/books/all")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_accepts_search_param(self, admin_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/books/all?search=test")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_accepts_filter_params(self, admin_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/books/all?tag=sci-fi&author=Asimov&series=Foundation"
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_accepts_sort_params(self, admin_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/books/all?sort=display_title&order=asc")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_accepts_pagination_params(self, admin_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/books/all?limit=20&offset=40")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_rejects_invalid_limit(self, admin_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/books/all?limit=0")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_rejects_negative_offset(self, admin_user):
        db = _mock_db_returning([], 0)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/books/all?offset=-1")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        """Ensure endpoint returns 401 without auth."""
        app.dependency_overrides.clear()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/books/all")
        # Should return 401 or redirect — not 200
        assert resp.status_code in (401, 403, 307)
