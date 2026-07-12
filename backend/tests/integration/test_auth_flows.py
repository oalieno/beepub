"""Session lifecycle beyond a single login: password change, refresh, logout."""

import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import USER_CREDENTIALS

pytestmark = pytest.mark.integration


def _fresh_client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")


async def test_change_password(user_client):
    response = await user_client.put(
        "/api/auth/change-password",
        json={
            "current_password": USER_CREDENTIALS["password"],
            "new_password": "brand-new-password-1",
        },
    )
    assert response.status_code == 200, response.text

    async with _fresh_client() as c:
        old = await c.post("/api/auth/login", data=USER_CREDENTIALS)
        assert old.status_code == 401
        new = await c.post(
            "/api/auth/login",
            data={
                "username": USER_CREDENTIALS["username"],
                "password": "brand-new-password-1",
            },
        )
        assert new.status_code == 200


async def test_wrong_current_password_rejected(user_client):
    response = await user_client.put(
        "/api/auth/change-password",
        json={"current_password": "not-the-password", "new_password": "whatever-123"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect"


async def test_refresh_issues_a_working_access_token(admin_client):
    # The login stored a refresh_token cookie on this client.
    response = await admin_client.post("/api/auth/refresh")
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    async with _fresh_client() as c:
        me = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200


async def test_logout_clears_the_session(admin_client):
    assert (await admin_client.get("/api/auth/me")).status_code == 200
    await admin_client.post("/api/auth/logout")
    assert (await admin_client.get("/api/auth/me")).status_code == 401


async def test_login_response_carries_permission_flags(user_client):
    """Native clients build (and cache) their whole user object from the
    login response — a missing flag silently hides UI gated on it."""
    async with _fresh_client() as c:
        response = await c.post("/api/auth/login", data=USER_CREDENTIALS)
        assert response.status_code == 200
        body = response.json()
        assert body["can_download"] is True
        assert isinstance(body["can_upload"], bool)
