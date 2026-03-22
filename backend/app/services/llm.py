from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

import httpx


@dataclass
class ChatMessage:
    """Standard chat message format (OpenAI/Anthropic convention)."""

    role: str  # "user" or "assistant"
    content: str


@dataclass
class TokenUsage:
    """Token usage from an LLM API call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Response from a non-streaming LLM call."""

    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)


class LLMStream:
    """Async iterator wrapper that yields text chunks and exposes .usage after iteration."""

    def __init__(self, iterator: AsyncIterator[str]) -> None:
        self._iterator = iterator
        self.usage: TokenUsage = TokenUsage()

    def __aiter__(self) -> LLMStream:
        return self

    async def __anext__(self) -> str:
        return await self._iterator.__anext__()


class LLMProvider(Protocol):
    async def generate(
        self, prompt: str, *, system: str | None = None
    ) -> LLMResponse: ...
    async def stream(self, prompt: str, *, system: str | None = None) -> LLMStream: ...
    async def chat(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> LLMResponse: ...
    async def chat_stream(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> LLMStream: ...


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

    @staticmethod
    def _parse_gemini_usage(data: dict) -> TokenUsage:
        meta = data.get("usageMetadata", {})
        return TokenUsage(
            input_tokens=meta.get("promptTokenCount", 0),
            output_tokens=meta.get("candidatesTokenCount", 0),
            total_tokens=meta.get("totalTokenCount", 0),
        )

    async def generate(self, prompt: str, *, system: str | None = None) -> LLMResponse:
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
        text = "".join(p["text"] for p in parts if "text" in p)
        return LLMResponse(text=text, usage=self._parse_gemini_usage(data))

    async def stream(self, prompt: str, *, system: str | None = None) -> LLMStream:
        url = f"{self._base_url}/models/{self._model}:streamGenerateContent?alt=sse"
        body = self._build_body(prompt, system)
        llm_stream = LLMStream(self._iter_placeholder())
        llm_stream._iterator = self._stream_gemini(url, body, llm_stream)
        return llm_stream

    async def chat(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> LLMResponse:
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
        text = "".join(p["text"] for p in parts if "text" in p)
        return LLMResponse(text=text, usage=self._parse_gemini_usage(data))

    async def chat_stream(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> LLMStream:
        url = f"{self._base_url}/models/{self._model}:streamGenerateContent?alt=sse"
        body = self._build_chat_body(messages, system)
        llm_stream = LLMStream(self._iter_placeholder())
        llm_stream._iterator = self._stream_gemini(url, body, llm_stream)
        return llm_stream

    @staticmethod
    async def _iter_placeholder() -> AsyncIterator[str]:
        return
        yield  # make it an async generator

    async def _stream_gemini(
        self, url: str, body: dict, llm_stream: LLMStream
    ) -> AsyncIterator[str]:
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
                    # Gemini returns usageMetadata in the last chunk
                    if "usageMetadata" in payload:
                        llm_stream.usage = self._parse_gemini_usage(payload)
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

    @staticmethod
    def _parse_openai_usage(data: dict) -> TokenUsage:
        usage = data.get("usage", {})
        return TokenUsage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )

    async def generate(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        url = f"{self._base_url}/chat/completions"
        body = {"model": self._model, "messages": self._build_messages(prompt, system)}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._build_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return LLMResponse(text=text, usage=self._parse_openai_usage(data))

    async def stream(self, prompt: str, *, system: str | None = None) -> LLMStream:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
            "messages": self._build_messages(prompt, system),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        llm_stream = LLMStream(self._iter_placeholder())
        llm_stream._iterator = self._stream_openai(url, body, llm_stream)
        return llm_stream

    async def chat(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> LLMResponse:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
            "messages": self._build_chat_messages(messages, system),
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._build_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return LLMResponse(text=text, usage=self._parse_openai_usage(data))

    async def chat_stream(
        self, messages: list[ChatMessage], *, system: str | None = None
    ) -> LLMStream:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
            "messages": self._build_chat_messages(messages, system),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        llm_stream = LLMStream(self._iter_placeholder())
        llm_stream._iterator = self._stream_openai(url, body, llm_stream)
        return llm_stream

    @staticmethod
    async def _iter_placeholder() -> AsyncIterator[str]:
        return
        yield  # make it an async generator

    async def _stream_openai(
        self, url: str, body: dict, llm_stream: LLMStream
    ) -> AsyncIterator[str]:
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
                    # OpenAI returns usage in a separate final chunk
                    if payload.get("usage"):
                        llm_stream.usage = self._parse_openai_usage(payload)
                    choices = payload.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content


class LLMNotConfiguredError(Exception):
    """Raised when no LLM provider is configured."""


def get_llm_provider_from_settings(
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
) -> LLMProvider:
    """Create an LLM provider from explicit settings."""
    if not provider:
        raise LLMNotConfiguredError("AI provider is not configured")
    if not model:
        raise LLMNotConfiguredError("AI model is not configured")

    if provider == "gemini":
        if not api_key:
            raise LLMNotConfiguredError("Gemini API key is not configured")
        return GeminiProvider(api_key=api_key, model=model)
    if provider == "openai":
        return OpenAICompatibleProvider(
            api_key=api_key,
            model=model,
            base_url=base_url or "https://api.openai.com/v1",
        )
    raise ValueError(f"Unknown LLM provider: {provider}")


def _resolve_credentials(db_settings: dict[str, str], provider: str) -> tuple[str, str]:
    """Get api_key and base_url for a provider type from shared credentials."""
    if provider == "gemini":
        return db_settings.get("gemini_api_key", ""), ""
    if provider == "openai":
        return db_settings.get("openai_api_key", ""), db_settings.get(
            "openai_base_url", ""
        )
    return "", ""


def get_companion_provider(db_settings: dict[str, str]) -> LLMProvider:
    """Create the companion LLM provider from DB settings."""
    provider = db_settings.get("companion_provider", "")
    model = db_settings.get("companion_model", "")
    api_key, base_url = _resolve_credentials(db_settings, provider)
    return get_llm_provider_from_settings(provider, api_key, model, base_url)


def get_tag_provider(db_settings: dict[str, str]) -> LLMProvider:
    """Create the tag LLM provider from DB settings."""
    provider = db_settings.get("tag_provider", "")
    model = db_settings.get("tag_model", "")
    api_key, base_url = _resolve_credentials(db_settings, provider)
    return get_llm_provider_from_settings(provider, api_key, model, base_url)


def get_image_provider(db_settings: dict[str, str]) -> LLMProvider:
    """Create the image LLM provider from DB settings."""
    provider = db_settings.get("image_provider", "")
    model = db_settings.get("image_model", "")
    api_key, base_url = _resolve_credentials(db_settings, provider)
    return get_llm_provider_from_settings(provider, api_key, model, base_url)
