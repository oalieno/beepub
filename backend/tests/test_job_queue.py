"""Tests for app.services.job_queue — JOB_TYPES registry and run_id logic."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.job_queue import (
    JOB_TYPES,
    STOPPED_SENTINEL,
    is_run_active,
    start_job_run,
    stop_job_run,
)


class TestJobTypes:
    def test_has_five_types(self):
        assert len(JOB_TYPES) == 5

    def test_expected_keys(self):
        expected = {
            "text_extraction",
            "embedding",
            "summarize",
            "auto_tag",
            "word_count",
        }
        assert set(JOB_TYPES.keys()) == expected

    def test_each_has_label_and_description(self):
        for key, jt in JOB_TYPES.items():
            assert jt.key == key
            assert len(jt.label) > 0
            assert len(jt.description) > 0


class TestStartJobRun:
    @pytest.mark.asyncio
    async def test_returns_uuid_string(self):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.job_queue.aioredis.from_url", return_value=mock_client
        ):
            run_id = await start_job_run("text_extraction")

        assert len(run_id) == 36  # UUID format
        mock_client.set.assert_called_once()


class TestStopJobRun:
    @pytest.mark.asyncio
    async def test_returns_true_when_active(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=b"some-run-id")
        mock_client.set = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.job_queue.aioredis.from_url", return_value=mock_client
        ):
            result = await stop_job_run("embedding")

        assert result is True
        # Should set to stopped sentinel
        call_args = mock_client.set.call_args
        assert call_args[0][1] == STOPPED_SENTINEL

    @pytest.mark.asyncio
    async def test_returns_false_when_not_active(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.job_queue.aioredis.from_url", return_value=mock_client
        ):
            result = await stop_job_run("embedding")

        assert result is False


class TestIsRunActive:
    @pytest.mark.asyncio
    async def test_active_when_matching(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=b"run-123")
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.job_queue.aioredis.from_url", return_value=mock_client
        ):
            assert await is_run_active("embedding", "run-123") is True

    @pytest.mark.asyncio
    async def test_inactive_when_stopped(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=STOPPED_SENTINEL.encode())
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.job_queue.aioredis.from_url", return_value=mock_client
        ):
            assert await is_run_active("embedding", "run-123") is False

    @pytest.mark.asyncio
    async def test_inactive_when_replaced(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=b"different-run-456")
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.job_queue.aioredis.from_url", return_value=mock_client
        ):
            assert await is_run_active("embedding", "run-123") is False

    @pytest.mark.asyncio
    async def test_inactive_when_key_expired(self):
        """TTL expired — tasks should skip."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.job_queue.aioredis.from_url", return_value=mock_client
        ):
            assert await is_run_active("embedding", "run-123") is False
