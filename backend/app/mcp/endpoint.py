"""ASGI endpoint driving the MCP streamable-HTTP transport.

The SDK's session manager must be "running" (an open task group) before
it can handle requests, and its run() may only be entered once. Tying
that to the FastAPI lifespan breaks under test transports that skip
lifespan (httpx ASGITransport) and under per-test event loops — so the
manager is started lazily, once per event loop, and parked in a
background task. Stateless + JSON responses: every request is
self-contained, nothing session-shaped to lose.
"""

import asyncio

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


class MCPEndpoint:
    def __init__(self, fastmcp):
        self._fastmcp = fastmcp
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._manager: StreamableHTTPSessionManager | None = None
        self._runner: asyncio.Task | None = None

    async def _ensure_manager(self) -> StreamableHTTPSessionManager:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # New loop (tests): the old manager died with its loop.
            self._loop = loop
            self._lock = asyncio.Lock()
            self._manager = None
            self._runner = None
        assert self._lock is not None
        async with self._lock:
            if self._manager is None:
                manager = StreamableHTTPSessionManager(
                    app=self._fastmcp._mcp_server,
                    json_response=True,
                    stateless=True,
                )
                started: asyncio.Event = asyncio.Event()

                async def runner():
                    try:
                        async with manager.run():
                            started.set()
                            await loop.create_future()  # park until closed
                    except asyncio.CancelledError:
                        pass

                self._runner = loop.create_task(runner())
                await started.wait()
                self._manager = manager
        return self._manager

    async def aclose(self) -> None:
        """Tear down the parked runner (tests call this between loops)."""
        if self._runner is not None:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
        self._loop = self._lock = self._manager = self._runner = None

    async def __call__(self, scope, receive, send):
        manager = await self._ensure_manager()
        await manager.handle_request(scope, receive, send)
