import json
from collections.abc import AsyncIterator

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
