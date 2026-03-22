"""Tests for LLM usage monitoring — provider return types and usage logging."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm import (
    GeminiProvider,
    LLMResponse,
    LLMStream,
    OpenAICompatibleProvider,
    TokenUsage,
)

# ---------------------------------------------------------------------------
# TokenUsage / LLMResponse / LLMStream dataclasses
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_defaults_to_zero(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_custom_values(self):
        usage = TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30)
        assert usage.input_tokens == 10
        assert usage.output_tokens == 20
        assert usage.total_tokens == 30


class TestLLMResponse:
    def test_text_and_usage(self):
        resp = LLMResponse(text="hello", usage=TokenUsage(10, 5, 15))
        assert resp.text == "hello"
        assert resp.usage.total_tokens == 15

    def test_default_usage(self):
        resp = LLMResponse(text="hello")
        assert resp.usage.total_tokens == 0


class TestLLMStream:
    @pytest.mark.asyncio
    async def test_yields_text_and_exposes_usage(self):
        async def gen():
            yield "hello "
            yield "world"

        stream = LLMStream(gen())
        assert stream.usage.total_tokens == 0

        chunks = []
        async for chunk in stream:
            chunks.append(chunk)

        assert chunks == ["hello ", "world"]


# ---------------------------------------------------------------------------
# GeminiProvider — usage parsing
# ---------------------------------------------------------------------------


def _gemini_response(text: str = "response", usage: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    data = {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
    }
    if usage:
        data["usageMetadata"] = usage
    resp.json.return_value = data
    return resp


class TestGeminiProviderUsage:
    @pytest.mark.asyncio
    async def test_generate_returns_llm_response_with_usage(self):
        mock_resp = _gemini_response(
            "hello",
            {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
        )
        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")
            result = await provider.generate("test prompt")

        assert isinstance(result, LLMResponse)
        assert result.text == "hello"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5
        assert result.usage.total_tokens == 15

    @pytest.mark.asyncio
    async def test_generate_missing_usage_metadata(self):
        mock_resp = _gemini_response("hello")  # no usageMetadata
        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")
            result = await provider.generate("test prompt")

        assert result.text == "hello"
        assert result.usage.input_tokens == 0
        assert result.usage.total_tokens == 0

    @pytest.mark.asyncio
    async def test_chat_returns_llm_response_with_usage(self):
        mock_resp = _gemini_response(
            "reply",
            {
                "promptTokenCount": 100,
                "candidatesTokenCount": 50,
                "totalTokenCount": 150,
            },
        )
        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            from app.services.llm import ChatMessage

            provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")
            result = await provider.chat([ChatMessage(role="user", content="hi")])

        assert isinstance(result, LLMResponse)
        assert result.text == "reply"
        assert result.usage.total_tokens == 150


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider — usage parsing
# ---------------------------------------------------------------------------


def _openai_response(text: str = "response", usage: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    data = {
        "choices": [{"message": {"content": text}}],
    }
    if usage:
        data["usage"] = usage
    resp.json.return_value = data
    return resp


class TestOpenAIProviderUsage:
    @pytest.mark.asyncio
    async def test_generate_returns_llm_response_with_usage(self):
        mock_resp = _openai_response(
            "hello",
            {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        )
        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key", model="gpt-4", base_url="http://localhost:11434/v1"
            )
            result = await provider.generate("test prompt")

        assert isinstance(result, LLMResponse)
        assert result.text == "hello"
        assert result.usage.input_tokens == 20
        assert result.usage.output_tokens == 10
        assert result.usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_generate_missing_usage(self):
        mock_resp = _openai_response("hello")  # no usage
        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            provider = OpenAICompatibleProvider(api_key="test-key", model="gpt-4")
            result = await provider.generate("test prompt")

        assert result.text == "hello"
        assert result.usage.total_tokens == 0


# ---------------------------------------------------------------------------
# Embedding — usage returned alongside vectors
# ---------------------------------------------------------------------------


class TestEmbeddingUsage:
    @pytest.mark.asyncio
    async def test_embed_texts_returns_usage_from_count_tokens(self):
        from app.services.embedding import embed_texts

        embed_resp = MagicMock()
        embed_resp.raise_for_status = MagicMock()
        embed_resp.json.return_value = {
            "embeddings": [{"values": [1.0, 0.0, 0.0]}],
        }
        count_resp = MagicMock()
        count_resp.status_code = 200
        count_resp.json.return_value = {"totalTokens": 42}

        async def _side_effect(url, **kwargs):
            if "countTokens" in url:
                return count_resp
            return embed_resp

        mock_post = AsyncMock(side_effect=_side_effect)
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            vectors, usage = await embed_texts(["test"], api_key="k")

        assert len(vectors) == 1
        assert usage.input_tokens == 42
        assert usage.output_tokens == 0
        assert usage.total_tokens == 42


# ---------------------------------------------------------------------------
# log_llm_usage — fire-and-forget
# ---------------------------------------------------------------------------


class TestLogLlmUsage:
    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_error(self):
        """log_llm_usage should swallow exceptions and never raise."""
        from app.services.llm_usage import log_llm_usage

        # Mock the session factory to raise
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(
            side_effect=Exception("DB connection failed")
        )
        mock_session_factory = MagicMock(return_value=mock_session)

        # Should not raise
        await log_llm_usage(
            feature="test",
            provider="gemini",
            model="test-model",
            usage=TokenUsage(10, 5, 15),
            session_factory=mock_session_factory,
        )
