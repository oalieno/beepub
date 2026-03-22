"""Tests for app.services.embedding — vector normalization and API calls."""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embedding import _normalize, embed_text, embed_texts

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
        vec = [float(i) for i in range(1, 769)]  # 768-dim like real embeddings
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
# embed_texts
# ---------------------------------------------------------------------------


def _fake_embed_response(vectors: list[list[float]]) -> MagicMock:
    """Build a mock httpx.Response for batchEmbedContents."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"embeddings": [{"values": v} for v in vectors]}
    return resp


def _fake_count_response(total_tokens: int = 42) -> MagicMock:
    """Build a mock httpx.Response for countTokens."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"totalTokens": total_tokens}
    return resp


def _make_mock_post(vectors: list[list[float]], total_tokens: int = 42) -> AsyncMock:
    """Mock post that routes by URL: embed vs countTokens."""

    async def _side_effect(url, **kwargs):
        if "countTokens" in url:
            return _fake_count_response(total_tokens)
        return _fake_embed_response(vectors)

    return AsyncMock(side_effect=_side_effect)


def _make_mock_client(mock_post: AsyncMock) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _get_embed_call(mock_post: AsyncMock):
    """Return the call_args for the batchEmbedContents call (first call)."""
    for call in mock_post.call_args_list:
        url = call[0][0]
        if "batchEmbedContents" in url:
            return call
    return mock_post.call_args_list[0]


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_returns_empty_list_for_empty_input(self):
        result, usage = await embed_texts([], api_key="fake-key")
        assert result == []
        assert usage.total_tokens == 0

    @pytest.mark.asyncio
    async def test_single_text_request_formation(self):
        raw_vector = [3.0, 4.0, 0.0]
        mock_post = _make_mock_post([raw_vector], total_tokens=5)
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            result, usage = await embed_texts(
                ["hello world"], api_key="test-key", model="gemini-embedding-001"
            )

        # Verify the embed POST was called with correct URL and body
        call_args = _get_embed_call(mock_post)
        url = call_args[0][0]
        assert "gemini-embedding-001:batchEmbedContents" in url

        body = call_args[1]["json"]
        assert len(body["requests"]) == 1
        assert body["requests"][0]["content"]["parts"][0]["text"] == "hello world"
        assert body["requests"][0]["outputDimensionality"] == 768

        # Verify API key header
        headers = call_args[1]["headers"]
        assert headers["x-goog-api-key"] == "test-key"

        # Verify result is normalized
        assert len(result) == 1
        norm = math.sqrt(sum(x * x for x in result[0]))
        assert abs(norm - 1.0) < 1e-9

        # Verify usage from countTokens
        assert usage.input_tokens == 5
        assert usage.total_tokens == 5

    @pytest.mark.asyncio
    async def test_batch_multiple_texts(self):
        raw_vectors = [[1.0, 0.0], [0.0, 2.0], [3.0, 4.0]]
        mock_post = _make_mock_post(raw_vectors, total_tokens=15)
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            result, usage = await embed_texts(
                ["text one", "text two", "text three"], api_key="k"
            )

        assert len(result) == 3

        # Each returned vector should be L2-normalized
        for vec in result:
            norm = math.sqrt(sum(x * x for x in vec))
            assert abs(norm - 1.0) < 1e-9

        # Verify all three texts were sent in one request
        call_args = _get_embed_call(mock_post)
        body = call_args[1]["json"]
        assert len(body["requests"]) == 3

        assert usage.input_tokens == 15
        assert usage.total_tokens == 15

    @pytest.mark.asyncio
    async def test_custom_model_and_dimensionality(self):
        mock_post = _make_mock_post([[1.0, 0.0, 0.0, 0.0]])
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_texts(
                ["test"], api_key="k", model="custom-model", dimensionality=256
            )

        call_args = _get_embed_call(mock_post)
        url = call_args[0][0]
        assert "custom-model:batchEmbedContents" in url

        body = call_args[1]["json"]
        assert body["requests"][0]["model"] == "models/custom-model"
        assert body["requests"][0]["outputDimensionality"] == 256

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
                await embed_texts(["fail"], api_key="k")


# ---------------------------------------------------------------------------
# embed_text  (single-text convenience wrapper)
# ---------------------------------------------------------------------------


class TestEmbedText:
    @pytest.mark.asyncio
    async def test_returns_single_vector(self):
        raw_vector = [0.0, 5.0]
        mock_post = _make_mock_post([raw_vector], total_tokens=3)
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            result, usage = await embed_text("single text", api_key="k")

        # Should return a flat list, not a list of lists
        assert isinstance(result, list)
        assert isinstance(result[0], float)

        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_passes_model_and_dimensionality(self):
        mock_post = _make_mock_post([[1.0]], total_tokens=1)
        mock_client = _make_mock_client(mock_post)

        with patch(
            "app.services.embedding.httpx.AsyncClient", return_value=mock_client
        ):
            await embed_text("x", api_key="k", model="m", dimensionality=32)

        call_args = _get_embed_call(mock_post)
        body = call_args[1]["json"]
        assert body["requests"][0]["model"] == "models/m"
        assert body["requests"][0]["outputDimensionality"] == 32
