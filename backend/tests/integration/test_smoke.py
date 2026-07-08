"""Smoke: the real app boots against real Postgres and auth round-trips."""

import pytest

from tests.integration.conftest import ADMIN_CREDENTIALS

pytestmark = pytest.mark.integration


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_first_registered_user_becomes_admin(client):
    response = await client.post(
        "/api/auth/register", json={"username": "alice", "password": "password123"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "admin"


async def test_registration_closed_after_first_user(client):
    await client.post(
        "/api/auth/register", json={"username": "first", "password": "password123"}
    )
    response = await client.post(
        "/api/auth/register", json={"username": "second", "password": "password123"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Registration is currently closed"


async def test_login_cookie_authenticates_me(admin_client):
    response = await admin_client.get("/api/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == ADMIN_CREDENTIALS["username"]
    assert body["role"] == "admin"


async def test_wrong_password_rejected(admin_client, client):
    response = await client.post(
        "/api/auth/login",
        data={"username": ADMIN_CREDENTIALS["username"], "password": "wrong-password"},
    )
    assert response.status_code == 401


async def test_regular_user_cannot_reach_admin_api(user_client):
    response = await user_client.get("/api/admin/users")
    assert response.status_code == 403
