"""Tests for app.services.job_queue — generation-based run/stop and active counters."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.job_queue import (
    JOB_TYPES,
    decr_pending,
    get_generation,
    get_pending_count,
    incr_pending,
    is_current_generation,
    start_job,
    stop_job,
)


def _mock_redis(**overrides) -> MagicMock:
    """Create a mock Redis client with default stubs."""
    client = MagicMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock()
    client.incr = AsyncMock(return_value=1)
    client.incrby = AsyncMock(return_value=1)
    client.decr = AsyncMock(return_value=0)
    client.delete = AsyncMock()
    client.exists = AsyncMock(return_value=0)
    client.aclose = AsyncMock()
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


def _patch_redis(client):
    return patch("app.services.job_queue.aioredis.from_url", return_value=client)


class TestJobTypes:
    def test_has_six_types(self):
        assert len(JOB_TYPES) == 6

    def test_expected_keys(self):
        expected = {
            "text_extraction",
            "embedding",
            "summarize",
            "auto_tag",
            "book_embedding",
            "metadata_backfill",
        }
        assert set(JOB_TYPES.keys()) == expected

    def test_each_has_label_and_description(self):
        for key, jt in JOB_TYPES.items():
            assert jt.key == key
            assert len(jt.label) > 0
            assert len(jt.description) > 0

    def test_ai_jobs_flagged(self):
        assert not JOB_TYPES["text_extraction"].requires_ai
        assert JOB_TYPES["embedding"].requires_ai
        assert JOB_TYPES["summarize"].requires_ai
        assert JOB_TYPES["auto_tag"].requires_ai
        assert JOB_TYPES["book_embedding"].requires_ai
        assert not JOB_TYPES["metadata_backfill"].requires_ai


class TestStartJob:
    @pytest.mark.asyncio
    async def test_increments_generation(self):
        client = _mock_redis(incr=AsyncMock(return_value=3))
        with _patch_redis(client):
            gen = await start_job("text_extraction")
        assert gen == 3
        client.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_incrementing_values(self):
        client = _mock_redis()
        client.incr = AsyncMock(side_effect=[1, 2, 3])
        with _patch_redis(client):
            assert await start_job("embedding") == 1
            assert await start_job("embedding") == 2
            assert await start_job("embedding") == 3


class TestStopJob:
    @pytest.mark.asyncio
    async def test_increments_generation(self):
        client = _mock_redis(incr=AsyncMock(return_value=5))
        with _patch_redis(client):
            gen = await stop_job("embedding")
        assert gen == 5
        client.incr.assert_called_once()


class TestGetGeneration:
    @pytest.mark.asyncio
    async def test_returns_generation_when_exists(self):
        client = _mock_redis(get=AsyncMock(return_value=b"7"))
        with _patch_redis(client):
            gen = await get_generation("embedding")
        assert gen == 7

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_key(self):
        client = _mock_redis()
        with _patch_redis(client):
            gen = await get_generation("embedding")
        assert gen == 0


class TestIsCurrentGeneration:
    @pytest.mark.asyncio
    async def test_true_when_matching(self):
        client = _mock_redis(get=AsyncMock(return_value=b"5"))
        with _patch_redis(client):
            assert await is_current_generation("embedding", 5) is True

    @pytest.mark.asyncio
    async def test_false_when_different(self):
        client = _mock_redis(get=AsyncMock(return_value=b"6"))
        with _patch_redis(client):
            assert await is_current_generation("embedding", 5) is False

    @pytest.mark.asyncio
    async def test_false_when_no_key(self):
        client = _mock_redis()
        with _patch_redis(client):
            assert await is_current_generation("embedding", 5) is False


class TestPendingCounter:
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_incr_pending(self):
        client = _mock_redis(incrby=AsyncMock(return_value=3))
        with _patch_redis(client):
            count = await incr_pending("embedding")
        assert count == 3

    @pytest.mark.asyncio
    async def test_decr_pending(self):
        client = _mock_redis(decr=AsyncMock(return_value=2))
        with _patch_redis(client):
            count = await decr_pending("embedding")
        assert count == 2

    @pytest.mark.asyncio
    async def test_decr_pending_floors_at_zero(self):
        client = _mock_redis(decr=AsyncMock(return_value=-1))
        with _patch_redis(client):
            count = await decr_pending("embedding")
        assert count == 0
        client.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pending_count(self):
        client = _mock_redis(get=AsyncMock(return_value=b"5"))
        with _patch_redis(client):
            count = await get_pending_count("embedding")
        assert count == 5

    @pytest.mark.asyncio
    async def test_get_pending_count_zero_when_no_key(self):
        client = _mock_redis()
        with _patch_redis(client):
            count = await get_pending_count("embedding")
        assert count == 0
