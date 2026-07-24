"""Personal API tokens (routers/tokens.py + migration 057).

Boundary under test: management needs a web login; the bearer token
authenticates ONLY the opt-in surface (/api/tokens/verify here), never
the regular web API.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _create(client: AsyncClient, name: str = "laptop") -> dict:
    response = await client.post("/api/tokens", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_list_revoke_lifecycle(user_client: AsyncClient):
    created = await _create(user_client, "koreader")
    assert created["token"].startswith("bpk_")
    assert created["token_prefix"] == created["token"][:12]

    # The plaintext never comes back on list.
    response = await user_client.get("/api/tokens")
    assert response.status_code == 200
    rows = response.json()
    assert [row["name"] for row in rows] == ["koreader"]
    assert "token" not in rows[0]
    assert rows[0]["last_used_at"] is None

    response = await user_client.delete(f"/api/tokens/{created['id']}")
    assert response.status_code == 204
    response = await user_client.get("/api/tokens")
    assert response.json() == []


async def test_duplicate_names_are_rejected(user_client: AsyncClient):
    await _create(user_client, "koreader")
    response = await user_client.post("/api/tokens", json={"name": " koreader "})
    assert response.status_code == 409
    # Still exactly one token.
    assert len((await user_client.get("/api/tokens")).json()) == 1


async def test_verify_accepts_the_token_and_stamps_last_used(
    user_client: AsyncClient, client: AsyncClient
):
    created = await _create(user_client)
    headers = {"Authorization": f"Bearer {created['token']}"}

    response = await client.get("/api/tokens/verify", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["username"]

    response = await user_client.get("/api/tokens")
    assert response.json()[0]["last_used_at"] is not None


async def test_verify_rejects_bad_missing_and_revoked_tokens(
    user_client: AsyncClient, client: AsyncClient
):
    created = await _create(user_client)

    response = await client.get("/api/tokens/verify")
    assert response.status_code == 401
    response = await client.get(
        "/api/tokens/verify", headers={"Authorization": "Bearer bpk_wrong"}
    )
    assert response.status_code == 401

    await user_client.delete(f"/api/tokens/{created['id']}")
    response = await client.get(
        "/api/tokens/verify",
        headers={"Authorization": f"Bearer {created['token']}"},
    )
    assert response.status_code == 401


async def test_api_token_is_not_a_web_credential(
    user_client: AsyncClient, client: AsyncClient
):
    created = await _create(user_client)
    headers = {"Authorization": f"Bearer {created['token']}"}
    # The regular API must not accept it — a leaked token can read via
    # the MCP surface but can't act as the user on the web API, and in
    # particular can't mint more tokens.
    response = await client.get("/api/libraries", headers=headers)
    assert response.status_code == 401
    response = await client.post("/api/tokens", json={"name": "x"}, headers=headers)
    assert response.status_code == 401


async def test_tokens_are_scoped_to_their_owner(
    admin_client: AsyncClient, user_client: AsyncClient
):
    mine = await _create(user_client, "mine")
    theirs = await _create(admin_client, "theirs")

    # Each account lists only its own.
    names = [r["name"] for r in (await user_client.get("/api/tokens")).json()]
    assert names == ["mine"]

    # Deleting someone else's token 404s and leaves it alive.
    response = await user_client.delete(f"/api/tokens/{theirs['id']}")
    assert response.status_code == 404
    names = [r["name"] for r in (await admin_client.get("/api/tokens")).json()]
    assert names == ["theirs"]
    assert mine["id"] != theirs["id"]
