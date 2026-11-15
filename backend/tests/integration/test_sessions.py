"""Logins are rows: ending one, keeping one alive, letting one lapse."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.session import UserSession
from tests.integration.conftest import ADMIN_CREDENTIALS, USER_CREDENTIALS, _api_client

pytestmark = pytest.mark.integration

NEW_PASSWORD = "a-new-password-456"


async def _login(credentials: dict[str, str]):
    """Another device: its own client, its own cookies."""
    client = _api_client()
    response = await client.post("/api/auth/login", data=credentials)
    assert response.status_code == 200, response.text
    return client, response.json()


async def _me(client, **kwargs) -> int:
    return (await client.get("/api/auth/me", **kwargs)).status_code


async def _sessions() -> list[UserSession]:
    async with AsyncSessionLocal() as db:
        return list(await db.scalars(select(UserSession)))


async def _age_every_session(**ago) -> None:
    """Make every login look last used that long ago."""
    then = datetime.now(UTC) - timedelta(**ago)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(UserSession).values(
                last_used_at=then, expires_at=then + timedelta(days=30)
            )
        )
        await db.commit()


async def test_logging_out_ends_that_login_and_no_other(user_client):
    phone, phone_tokens = await _login(USER_CREDENTIALS)
    bearer = {"Authorization": f"Bearer {phone_tokens['access_token']}"}

    # The phone logs out the way the app does: its token in a header.
    async with _api_client() as app:
        assert await _me(app, headers=bearer) == 200
        response = await app.post("/api/auth/logout", headers=bearer)
        assert response.status_code == 200
        # The copy of its tokens is dead at once — not when they expire.
        assert await _me(app, headers=bearer) == 401
        refreshed = await app.post(
            "/api/auth/refresh",
            headers={"X-Refresh-Token": phone_tokens["refresh_token"]},
        )
        assert refreshed.status_code == 401
    await phone.aclose()

    assert await _me(user_client) == 200  # the browser is still signed in


async def test_logging_out_in_a_browser_ends_its_login(user_client):
    stolen = dict(user_client.cookies)
    assert (await user_client.post("/api/auth/logout")).status_code == 200
    async with _api_client() as thief:
        thief.cookies.update(stolen)
        assert await _me(thief) == 401


async def test_changing_the_password_ends_other_logins_and_keeps_this_one(user_client):
    phone, _ = await _login(USER_CREDENTIALS)
    response = await user_client.put(
        "/api/auth/change-password",
        json={
            "current_password": USER_CREDENTIALS["password"],
            "new_password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text

    assert await _me(user_client) == 200
    assert await _me(phone) == 401
    await phone.aclose()


async def test_an_admin_reset_ends_that_users_logins_only(admin_client, user_client):
    users = (await admin_client.get("/api/admin/users")).json()
    reader = next(u for u in users if u["username"] == USER_CREDENTIALS["username"])
    response = await admin_client.put(
        f"/api/admin/users/{reader['id']}/password",
        json={"new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text

    assert await _me(user_client) == 401
    assert await _me(admin_client) == 200


async def test_a_login_in_use_never_runs_out(admin_client):
    # Twenty-nine days without a request: one day short of lapsing.
    await _age_every_session(days=29)
    assert await _me(admin_client) == 200
    # That request counted as use: the thirty days start again from now.
    (session,) = await _sessions()
    assert session.expires_at > datetime.now(UTC) + timedelta(days=29)


async def test_a_login_left_unused_for_the_idle_period_ends(admin_client):
    await _age_every_session(days=31)
    assert await _me(admin_client) == 401
    assert (await admin_client.post("/api/auth/refresh")).status_code == 401


async def test_a_refresh_extends_the_login_and_says_how_long_the_token_lasts(
    admin_client,
):
    await _age_every_session(minutes=5)  # (too recent for a request to touch)
    response = await admin_client.post("/api/auth/refresh")
    assert response.status_code == 200, response.text
    assert response.json()["expires_in"] > 0
    (session,) = await _sessions()
    assert datetime.now(UTC) - session.last_used_at < timedelta(minutes=1)
    # The refresh cookie is set again, for the whole site.
    cookie = next(c for c in admin_client.cookies.jar if c.name == "refresh_token")
    assert cookie.path == "/"


async def test_a_token_that_names_no_login_is_refused(admin_client):
    """What every token from before this change is."""
    from app.services.auth import create_access_token

    users = (await admin_client.get("/api/admin/users")).json()
    admin = next(u for u in users if u["username"] == ADMIN_CREDENTIALS["username"])
    old_style = create_access_token({"sub": admin["id"]})
    async with _api_client() as bearer:
        assert (
            await _me(bearer, headers={"Authorization": f"Bearer {old_style}"}) == 401
        )


async def test_signing_in_clears_away_logins_that_ran_out(admin_client):
    await _age_every_session(days=40)
    again, _ = await _login(ADMIN_CREDENTIALS)
    assert len(await _sessions()) == 1
    await again.aclose()
