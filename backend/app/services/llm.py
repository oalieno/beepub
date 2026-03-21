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
    async def stream(
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[str]: ...
    async def chat(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> str: ...
    async def chat_stream(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> AsyncIterator[str]: ...


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

    async def stream(
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[str]:
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

    async def chat(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> str:
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

    async def chat_stream(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> AsyncIterator[str]:
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


class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible APIs (OpenAI, Ollama, LiteLLM, etc.)."""

    def __init__(
        self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _build_messages(self, prompt: str, system: str | None) -> list[dict]:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    def _build_chat_messages(
        self, messages: list[ChatMessage], system: str | None
    ) -> list[dict]:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend({"role": m.role, "content": m.content} for m in messages)
        return msgs

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        url = f"{self._base_url}/chat/completions"
        body = {"model": self._model, "messages": self._build_messages(prompt, system)}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._build_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream(
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[str]:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
            "messages": self._build_messages(prompt, system),
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", url, headers=self._build_headers(), json=body
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line.removeprefix("data: ").strip()
                    if data_str == "[DONE]":
                        break
                    payload = json.loads(data_str)
                    delta = payload.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

    async def chat(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
            "messages": self._build_chat_messages(messages, system),
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._build_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def chat_stream(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> AsyncIterator[str]:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
            "messages": self._build_chat_messages(messages, system),
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", url, headers=self._build_headers(), json=body
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line.removeprefix("data: ").strip()
                    if data_str == "[DONE]":
                        break
                    payload = json.loads(data_str)
                    delta = payload.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content


def get_llm_provider(overrides: dict[str, str] | None = None) -> LLMProvider:
    """Create LLM provider. DB settings override .env defaults."""
    o = overrides or {}
    provider = o.get("llm_provider", settings.llm_provider)

    if provider == "gemini":
        return GeminiProvider(
            api_key=o.get("gemini_api_key", settings.gemini_api_key),
            model=o.get("gemini_model", settings.gemini_model),
        )
    if provider == "openai":
        return OpenAICompatibleProvider(
            api_key=o.get("openai_api_key", settings.openai_api_key),
            model=o.get("openai_model", settings.openai_model),
            base_url=o.get("openai_base_url", settings.openai_base_url),
        )
    raise ValueError(f"Unknown LLM provider: {provider}")
