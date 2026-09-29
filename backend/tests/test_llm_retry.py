"""Tests for GeminiProvider streaming retries while Gemini is busy."""

import json
from unittest.mock import patch

import httpx
import pytest

from app.services.llm import GeminiProvider, LLMBusyError, LLMStream


class _BrokenAfterFirstLine(httpx.AsyncByteStream):
    """A stream that sends one SSE line and then drops the connection."""

    async def __aiter__(self):
        yield b'data: {"candidates": [{"content": {"parts": [{"text": "Hel"}]}}]}\n\n'
        raise httpx.ReadError("connection dropped")


def _patch_client(responses: list[httpx.Response]):
    """Patch AsyncClient to answer each streaming call with the next response."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses[len(calls) - 1]

    real_client = httpx.AsyncClient

    def factory(**_kw):
        return real_client(transport=httpx.MockTransport(handler))

    return patch("app.services.llm.httpx.AsyncClient", side_effect=factory), calls


def _sse_ok(text: str) -> httpx.Response:
    line = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]})
    return httpx.Response(200, content=f"data: {line}\n\n".encode())


async def _collect(stream: LLMStream) -> str:
    return "".join([chunk async for chunk in stream])


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(GeminiProvider, "_RETRY_DELAYS", (0.0, 0.0))


async def test_busy_twice_then_answers():
    patcher, calls = _patch_client(
        [httpx.Response(503), httpx.Response(429), _sse_ok("hello")]
    )
    with patcher:
        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash")
        text = await _collect(await provider.stream("hi"))

    assert text == "hello"
    assert len(calls) == 3


async def test_always_busy_raises_busy_error():
    patcher, calls = _patch_client([httpx.Response(503)] * 3)
    with patcher:
        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash")
        with pytest.raises(LLMBusyError):
            await _collect(await provider.stream("hi"))

    assert len(calls) == 3


async def test_other_errors_are_not_retried():
    patcher, calls = _patch_client([httpx.Response(400)])
    with patcher:
        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash")
        with pytest.raises(httpx.HTTPStatusError):
            await _collect(await provider.stream("hi"))

    assert len(calls) == 1


async def test_failure_after_first_token_is_not_retried():
    patcher, calls = _patch_client(
        [httpx.Response(200, stream=_BrokenAfterFirstLine()), _sse_ok("again")]
    )
    chunks: list[str] = []
    with patcher:
        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash")
        with pytest.raises(httpx.ReadError):
            async for chunk in await provider.stream("hi"):
                chunks.append(chunk)

    assert chunks == ["Hel"]
    assert len(calls) == 1


async def test_companion_stream_reports_busy_code():
    import uuid

    from app.routers.companion import _streaming_generator

    async def busy():
        raise LLMBusyError("Gemini is busy")
        yield  # make it an async generator

    events = [
        e
        async for e in _streaming_generator(
            LLMStream(busy()),
            uuid.uuid4(),
            uuid.uuid4(),
            user_id=uuid.uuid4(),
            book_id=uuid.uuid4(),
            provider_name="gemini",
            model_name="gemini-2.0-flash",
        )
    ]

    assert len(events) == 1
    assert events[0].startswith("event: error\n")
    assert '"code": "llm_busy"' in events[0]
