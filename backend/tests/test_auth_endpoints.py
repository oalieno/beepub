"""Tests for auth API endpoints — login, logout, me, register.

These tests verify HttpOnly cookie-based auth flow end-to-end using
httpx AsyncClient against the real FastAPI app with a mocked database.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.user import User, UserRole
from app.services.auth import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    hash_password,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    username: str = "testuser",
    password: str = "testpass",
    role: UserRole = UserRole.user,
    is_active: bool = True,
) -> User:
    """Build a User ORM object with hashed password."""
    user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
        can_download=False,
    )
    user.created_at = datetime.now(UTC)
    return user


def _mock_db_session(users: list[User] | None = None, user_count: int = 1):
    """Return a mock AsyncSession that responds to auth-router queries.

    Inspects the SQLAlchemy statement's compiled bind parameters to match
    the correct user, since str(stmt) doesn't contain literal values.
    """
    users = users or []
    user_by_username = {u.username: u for u in users}
    user_by_id = {str(u.id): u for u in users}

    session = AsyncMock()

    async def fake_execute(stmt):
        result = MagicMock()

        # Extract bind params from compiled statement
        try:
            compiled = stmt.compile()
            params = compiled.params
        except Exception:
            params = {}

        # Check what columns are in the WHERE clause by looking at params
        # SQLAlchemy generates param names like 'username_1', 'id_1', etc.
        username_param = None
        id_param = None
        is_count = False

        for key, val in params.items():
            if "username" in key:
                username_param = val
            if key.startswith("id"):
                id_param = str(val) if val else None

        # Detect COUNT queries by checking the statement columns
        try:
            stmt_str = str(compiled)
            is_count = "count" in stmt_str.lower()
        except Exception:
            pass

        if is_count:
            result.scalar.return_value = user_count
            return result

        if username_param is not None:
            result.scalar_one_or_none.return_value = user_by_username.get(
                username_param
            )
            return result

        if id_param is not None:
            result.scalar_one_or_none.return_value = user_by_id.get(id_param)
            return result

        # Fallback: if no identifiable param, try matching by id from all params
        for key, val in params.items():
            str_val = str(val) if val else ""
            if str_val in user_by_id:
                result.scalar_one_or_none.return_value = user_by_id[str_val]
                return result

        result.scalar_one_or_none.return_value = None
        return result

    session.execute = fake_execute
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def test_user():
    return _make_user()


@pytest.fixture
def admin_user():
    return _make_user(username="admin", role=UserRole.admin)


@pytest.fixture
def inactive_user():
    return _make_user(username="inactive", is_active=False)


def _override_db(session):
    """Override the get_db dependency to return our mock session."""

    async def override():
        yield session

    app.dependency_overrides[get_db] = override


def _cleanup():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success_sets_httponly_cookie(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/auth/login",
                    data={"username": "testuser", "password": "testpass"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["username"] == "testuser"
            assert "id" in body

            # Check Set-Cookie headers — both access and refresh
            set_cookies = resp.headers.get_list("set-cookie")
            cookie_header = " ; ".join(set_cookies).lower()
            assert "token=" in cookie_header
            assert "refresh_token=" in cookie_header
            assert "httponly" in cookie_header
            assert "samesite=lax" in cookie_header
            # Refresh cookie is scoped to /api/auth
            assert any(
                "refresh_token=" in c.lower() and "path=/api/auth" in c.lower()
                for c in set_cookies
            )

            # Login response includes both tokens for SPA/Capacitor clients
            assert "access_token" in body
            assert isinstance(body["access_token"], str)
            assert len(body["access_token"]) > 0
            assert "refresh_token" in body
            assert isinstance(body["refresh_token"], str)
            assert len(body["refresh_token"]) > 0
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_login_wrong_password_no_cookie(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/auth/login",
                    data={"username": "testuser", "password": "wrongpass"},
                )
            assert resp.status_code == 401
            assert "set-cookie" not in resp.headers
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self):
        session = _mock_db_session(users=[])
        _override_db(session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/auth/login",
                    data={"username": "nobody", "password": "pass"},
                )
            assert resp.status_code == 401
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, inactive_user):
        session = _mock_db_session(users=[inactive_user])
        _override_db(session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/auth/login",
                    data={"username": "inactive", "password": "testpass"},
                )
            assert resp.status_code == 400
            assert "disabled" in resp.json()["detail"].lower()
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_login_returns_user_info_and_token(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/auth/login",
                    data={"username": "testuser", "password": "testpass"},
                )
            body = resp.json()
            assert body["username"] == "testuser"
            assert body["role"] == "user"
            assert body["is_active"] is True
            assert "id" in body
            assert "access_token" in body

            # Verify the token is a valid JWT that can auth /me
            token = body["access_token"]
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                me_resp = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert me_resp.status_code == 200
            assert me_resp.json()["username"] == "testuser"
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_clears_both_cookies(self):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/auth/logout")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

            set_cookies = resp.headers.get_list("set-cookie")
            joined = " ; ".join(set_cookies).lower()
            assert "token=" in joined
            assert "refresh_token=" in joined
            # Both should be expired (max-age=0 or past expires)
            for c in set_cookies:
                assert "max-age=0" in c.lower() or "expires=" in c.lower()
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# Me (cookie auth)
# ---------------------------------------------------------------------------


class TestMe:
    @pytest.mark.asyncio
    async def test_me_with_cookie(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            token = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"token": token},
            ) as client:
                resp = await client.get("/api/auth/me")
            assert resp.status_code == 200
            assert resp.json()["username"] == "testuser"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_me_with_bearer_header(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            token = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["username"] == "testuser"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_me_no_auth_returns_401(self):
        session = _mock_db_session(users=[])
        _override_db(session)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/auth/me")
            assert resp.status_code == 401
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_me_expired_token_returns_401(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            expired_token = jwt.encode(
                {
                    "sub": str(test_user.id),
                    "exp": datetime.now(UTC) - timedelta(hours=1),
                },
                settings.secret_key,
                algorithm=ALGORITHM,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"token": expired_token},
            ) as client:
                resp = await client.get("/api/auth/me")
            assert resp.status_code == 401
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_me_bearer_takes_precedence_over_cookie(self, test_user, admin_user):
        """When both Authorization header and cookie are present, header wins."""
        session = _mock_db_session(users=[test_user, admin_user])
        _override_db(session)
        try:
            header_token = create_access_token({"sub": str(admin_user.id)})
            cookie_token = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"token": cookie_token},
            ) as client:
                resp = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {header_token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["username"] == "admin"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_me_inactive_user_returns_401(self, inactive_user):
        session = _mock_db_session(users=[inactive_user])
        _override_db(session)
        try:
            token = create_access_token({"sub": str(inactive_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"token": token},
            ) as client:
                resp = await client.get("/api/auth/me")
            assert resp.status_code == 401
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_me_rejects_refresh_token(self, test_user):
        """A refresh token must NOT be usable as an access token."""
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            refresh = create_refresh_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {refresh}"},
                )
            assert resp.status_code == 401
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# Update username
# ---------------------------------------------------------------------------


class TestUpdateUsername:
    @pytest.mark.asyncio
    async def test_update_username_success(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            token = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/auth/username",
                    json={"new_username": "renamed"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["username"] == "renamed"
            assert test_user.username == "renamed"
            session.commit.assert_awaited_once()
            session.refresh.assert_awaited_once_with(test_user)
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_update_username_trims_whitespace(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            token = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/auth/username",
                    json={"new_username": "  renamed  "},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["username"] == "renamed"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_update_username_duplicate_returns_400(self, test_user):
        other_user = _make_user(username="taken")
        session = _mock_db_session(users=[test_user, other_user])
        _override_db(session)
        try:
            token = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/auth/username",
                    json={"new_username": "taken"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "Username already exists"
            session.commit.assert_not_awaited()
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_update_username_blank_returns_422(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            token = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/auth/username",
                    json={"new_username": "   "},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 422
            session.commit.assert_not_awaited()
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_via_cookie(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            refresh = create_refresh_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"refresh_token": refresh},
            ) as client:
                resp = await client.post("/api/auth/refresh")
            assert resp.status_code == 200
            body = resp.json()
            assert "access_token" in body and len(body["access_token"]) > 0

            # New access cookie set
            set_cookies = resp.headers.get_list("set-cookie")
            assert any("token=" in c.lower() for c in set_cookies)

            # The new access token actually works against /me
            new_access = body["access_token"]
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                me_resp = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {new_access}"},
                )
            assert me_resp.status_code == 200
            assert me_resp.json()["username"] == "testuser"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_refresh_via_header(self, test_user):
        """Native (Capacitor) clients send the refresh token via header."""
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            refresh = create_refresh_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/auth/refresh",
                    headers={"X-Refresh-Token": refresh},
                )
            assert resp.status_code == 200
            assert "access_token" in resp.json()
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_refresh_rejects_access_token(self, test_user):
        """An access token must NOT be usable on the refresh endpoint."""
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            access = create_access_token({"sub": str(test_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"refresh_token": access},
            ) as client:
                resp = await client.post("/api/auth/refresh")
            assert resp.status_code == 401
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_refresh_no_token_returns_401(self):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/auth/refresh")
            assert resp.status_code == 401
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_refresh_inactive_user_returns_401(self, inactive_user):
        session = _mock_db_session(users=[inactive_user])
        _override_db(session)
        try:
            refresh = create_refresh_token({"sub": str(inactive_user.id)})
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"refresh_token": refresh},
            ) as client:
                resp = await client.post("/api/auth/refresh")
            assert resp.status_code == 401
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_refresh_expired_token_returns_401(self, test_user):
        session = _mock_db_session(users=[test_user])
        _override_db(session)
        try:
            expired = jwt.encode(
                {
                    "sub": str(test_user.id),
                    "type": "refresh",
                    "exp": datetime.now(UTC) - timedelta(hours=1),
                },
                settings.secret_key,
                algorithm=ALGORITHM,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"refresh_token": expired},
            ) as client:
                resp = await client.post("/api/auth/refresh")
            assert resp.status_code == 401
        finally:
            _cleanup()
