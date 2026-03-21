import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse


async def _sse_event_generator(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    async for chunk in chunks:
        yield f"data: {json.dumps({'text': chunk})}\n\n"
    yield "data: [DONE]\n\n"


def sse_response(chunks: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        _sse_event_generator(chunks),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def sse_event(event_type: str, data: dict[str, Any] | str) -> str:
    """Format a single typed SSE event."""
    payload = json.dumps(data) if isinstance(data, dict) else data
    return f"event: {event_type}\ndata: {payload}\n\n"


async def _typed_sse_generator(
    chunks: AsyncIterator[str],
    *,
    on_done: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Stream tokens as typed SSE events, then send a 'done' event."""
    try:
        async for chunk in chunks:
            yield sse_event("token", {"text": chunk})
        yield sse_event("done", on_done or {})
    except Exception as exc:
        yield sse_event("error", {"message": str(exc)})


def typed_sse_response(
    chunks: AsyncIterator[str],
    *,
    on_done: dict[str, Any] | None = None,
) -> StreamingResponse:
    """Create a StreamingResponse with typed SSE events (token/done/error)."""
    return StreamingResponse(
        _typed_sse_generator(chunks, on_done=on_done),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
