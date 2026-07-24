"""ASGI auth gate for the MCP mount.

Every request under /mcp must carry a personal API token (bpk_…). The
authenticated user is stashed in the ASGI scope state, where tools pick
it up via the request context — the MCP surface never sees cookies or
web JWTs.
"""

import json

from app.database import AsyncSessionLocal
from app.routers.tokens import user_for_bearer_token


class MCPPathNormalizer:
    """App-level middleware: serve bare /mcp without a 307.

    Starlette's Mount regex only matches /mcp/…, so the router would
    slash-redirect POST /mcp — and many MCP clients don't follow
    redirects on POST. Rewriting the path before routing avoids it.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


class MCPAuthGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = ""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                authorization = value.decode("latin-1")
                break

        async with AsyncSessionLocal() as db:
            user = await user_for_bearer_token(db, authorization)

        if user is None:
            body = json.dumps({"error": "invalid or missing API token"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # The User instance is detached but its columns are loaded —
        # tools only read id/role/username.
        state = dict(scope.get("state") or {})
        state["mcp_user"] = user
        scope["state"] = state
        await self.app(scope, receive, send)
