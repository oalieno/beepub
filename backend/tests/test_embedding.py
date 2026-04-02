"""Tests for app.services.embedding — vector normalization and OpenAI-compatible API calls."""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embedding import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_PROMPT_QUERY,
    _normalize,
    embed_text,
    embed_texts,
)

# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_unit_vector_has_l2_norm_one(self):
        vec = [3.0, 4.0]
        result = _normalize(vec)
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-9

    def test_high_dimensional_vector(self):
        vec = [float(i) for i in range(1, 1025)]  # 1024-dim like real embeddings
        result = _normalize(vec)
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-9

    def test_already_normalized_vector_unchanged(self):
        vec = [1.0, 0.0, 0.0]
        result = _normalize(vec)
        assert abs(result[0] - 1.0) < 1e-9
        assert abs(result[1]) < 1e-9
        assert abs(result[2]) < 1e-9

    def test_zero_vector_returns_zero_vector(self):
        vec = [0.0, 0.0, 0.0]
        result = _normalize(vec)
        assert result == [0.0, 0.0, 0.0]

    def test_negative_values(self):
        vec = [-3.0, 4.0]
        result = _normalize(vec)
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-9
        assert result[0] < 0  # sign preserved

    def test_single_element(self):
        result = _normalize([5.0])
        assert abs(result[0] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# embed_texts (OpenAI-compatible /v1/embeddings)
# ---------------------------------------------------------------------------


def _fake_openai_response(
    vectors: list[list[float]], total_tokens: int = 42
) -> MagicMock:
    """Build a mock httpx.Response for /v1/embeddings."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)],
        "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    }
    return resp


def _make_mock_client(mock_post: AsyncMock) -> MagicMock:
    mock_client = MagicMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_returns_empty_list_for_empty_input(self):
        result, usage = await embed_texts(
            [], api_url="http://localhost:1234/v1", model="test"
        )
        assert result == []
        assert usage.total_tokens == 0

    @pytest.mark.asyncio
    async def test_single_text_request_formation(self):
        raw_vector = [3.0, 4.0, 0.0]
        mock_post = AsyncMock(
            return_value=_fake_openai_response([raw_vector], total_tokens=5)
        )
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            result, usage = await embed_texts(
                ["hello world"],
                api_url="http://localhost:1234/v1",
                model="qwen3-embedding",
            )

        # Verify the POST was called with correct URL and body
        call_args = mock_post.call_args
        url = call_args[0][0]
        assert url == "http://localhost:1234/v1/embeddings"

        body = call_args[1]["json"]
        assert body["model"] == "qwen3-embedding"
        assert body["input"] == ["hello world"]

        # Verify result is normalized
        assert len(result) == 1
        norm = math.sqrt(sum(x * x for x in result[0]))
        assert abs(norm - 1.0) < 1e-9

        # Verify usage
        assert usage.total_tokens == 5

    @pytest.mark.asyncio
    async def test_batch_multiple_texts(self):
        raw_vectors = [[1.0, 0.0], [0.0, 2.0], [3.0, 4.0]]
        mock_post = AsyncMock(
            return_value=_fake_openai_response(raw_vectors, total_tokens=15)
        )
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            result, usage = await embed_texts(
                ["text one", "text two", "text three"],
                api_url="http://localhost:1234/v1",
                model="m",
            )

        assert len(result) == 3

        # Each returned vector should be L2-normalized
        for vec in result:
            norm = math.sqrt(sum(x * x for x in vec))
            assert abs(norm - 1.0) < 1e-9

        # Verify all three texts were sent in one request
        body = mock_post.call_args[1]["json"]
        assert body["input"] == ["text one", "text two", "text three"]

        assert usage.total_tokens == 15

    @pytest.mark.asyncio
    async def test_passes_api_key_as_bearer(self):
        mock_post = AsyncMock(return_value=_fake_openai_response([[1.0, 0.0]]))
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_texts(
                ["test"],
                api_url="http://localhost:1234/v1",
                model="m",
                api_key="secret-key",
            )

        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer secret-key"

    @pytest.mark.asyncio
    async def test_no_auth_header_when_no_api_key(self):
        mock_post = AsyncMock(return_value=_fake_openai_response([[1.0, 0.0]]))
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_texts(
                ["test"],
                api_url="http://localhost:1234/v1",
                model="m",
            )

        headers = mock_post.call_args[1]["headers"]
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")

        mock_post = AsyncMock(return_value=mock_resp)
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(Exception, match="HTTP 500"):
                await embed_texts(
                    ["fail"],
                    api_url="http://localhost:1234/v1",
                    model="m",
                )

    @pytest.mark.asyncio
    async def test_prompt_included_in_body_when_provided(self):
        mock_post = AsyncMock(return_value=_fake_openai_response([[1.0, 0.0]]))
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_texts(
                ["test"],
                api_url="http://localhost:1234/v1",
                model="m",
                prompt="Instruct: test\nQuery: ",
            )

        body = mock_post.call_args[1]["json"]
        assert body["prompt"] == "Instruct: test\nQuery: "

    @pytest.mark.asyncio
    async def test_prompt_omitted_from_body_when_empty(self):
        mock_post = AsyncMock(return_value=_fake_openai_response([[1.0, 0.0]]))
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_texts(
                ["test"],
                api_url="http://localhost:1234/v1",
                model="m",
            )

        body = mock_post.call_args[1]["json"]
        assert "prompt" not in body

    @pytest.mark.asyncio
    async def test_sorts_by_index(self):
        """Verify embeddings are returned in input order even if API returns out of order."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ],
            "usage": {"total_tokens": 10},
        }
        mock_post = AsyncMock(return_value=resp)
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            result, _ = await embed_texts(
                ["first", "second"],
                api_url="http://localhost:1234/v1",
                model="m",
            )

        # index 0 should be [1.0, 0.0] normalized
        assert result[0][0] > result[0][1]
        # index 1 should be [0.0, 1.0] normalized
        assert result[1][1] > result[1][0]


# ---------------------------------------------------------------------------
# embed_text (single-text convenience wrapper)
# ---------------------------------------------------------------------------


class TestEmbedText:
    @pytest.mark.asyncio
    async def test_returns_single_vector(self):
        raw_vector = [0.0, 5.0]
        mock_post = AsyncMock(
            return_value=_fake_openai_response([raw_vector], total_tokens=3)
        )
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            result, usage = await embed_text(
                "single text",
                api_url="http://localhost:1234/v1",
                model="m",
            )

        # Should return a flat list, not a list of lists
        assert isinstance(result, list)
        assert isinstance(result[0], float)

        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_passes_prompt_through(self):
        mock_post = AsyncMock(
            return_value=_fake_openai_response([[1.0]], total_tokens=1)
        )
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_text(
                "x",
                api_url="http://localhost:1234/v1",
                model="m",
                prompt=EMBEDDING_PROMPT_QUERY,
            )

        body = mock_post.call_args[1]["json"]
        assert body["prompt"] == EMBEDDING_PROMPT_QUERY

    @pytest.mark.asyncio
    async def test_passes_model(self):
        mock_post = AsyncMock(
            return_value=_fake_openai_response([[1.0]], total_tokens=1)
        )
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_text(
                "x",
                api_url="http://localhost:1234/v1",
                model="custom-model",
            )

        body = mock_post.call_args[1]["json"]
        assert body["model"] == "custom-model"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_embedding_dimensions(self):
        assert EMBEDDING_DIMENSIONS == 1024
