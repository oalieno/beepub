from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import settings


@dataclass
class ChatMessage:
    """Standard chat message format (OpenAI/Anthropic convention)."""

    role: str  # "user" or "assistant"
    content: str


class LLMProvider(Protocol):
    async def generate(self, prompt: str, *, system: str | None = None) -> str: ...
    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]: ...
    async def chat(self, messages: list[ChatMessage], *, system: str | None = None) -> str: ...
    async def chat_stream(self, messages: list[ChatMessage], *, system: str | None = None) -> AsyncIterator[str]: ...


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _build_body(self, prompt: str, system: str | None) -> dict:
        body: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def _build_chat_body(self, messages: list[ChatMessage], system: str | None) -> dict:
        role_map = {"user": "user", "assistant": "model"}
        contents = [
            {"role": role_map.get(m.role, m.role), "parts": [{"text": m.content}]}
            for m in messages
        ]
        body: dict = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        url = f"{self._base_url}/models/{self._model}:generateContent"
        body = self._build_body(prompt, system)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers={"x-goog-api-key": self._api_key},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p["text"] for p in parts if "text" in p)

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        url = f"{self._base_url}/models/{self._model}:streamGenerateContent?alt=sse"
        body = self._build_body(prompt, system)
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                url,
                headers={"x-goog-api-key": self._api_key},
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = json.loads(line.removeprefix("data: "))
                    candidates = payload.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            yield part["text"]

    async def chat(self, messages: list[ChatMessage], *, system: str | None = None) -> str:
        url = f"{self._base_url}/models/{self._model}:generateContent"
        body = self._build_chat_body(messages, system)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers={"x-goog-api-key": self._api_key},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p["text"] for p in parts if "text" in p)

    async def chat_stream(self, messages: list[ChatMessage], *, system: str | None = None) -> AsyncIterator[str]:
        url = f"{self._base_url}/models/{self._model}:streamGenerateContent?alt=sse"
        body = self._build_chat_body(messages, system)
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                url,
                headers={"x-goog-api-key": self._api_key},
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = json.loads(line.removeprefix("data: "))
                    candidates = payload.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            yield part["text"]


def get_llm_provider() -> LLMProvider:
    if settings.llm_provider == "gemini":
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        )
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
