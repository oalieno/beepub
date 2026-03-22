"""Tests for app.services.job_queue — Redis job status + missing count queries."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.job_queue import (
    JOB_KEY_PREFIX,
    JOB_TTL_SECONDS,
    JOB_TYPES,
    _job_key,
    clear_job_status,
    get_all_job_statuses,
    get_job_status,
    set_job_status,
)

# ---------------------------------------------------------------------------
# _job_key
# ---------------------------------------------------------------------------

class TestJobKey:
    def test_format(self):
        assert _job_key("text_extraction") == f"{JOB_KEY_PREFIX}:text_extraction"

    def test_all_job_types_have_keys(self):
        for key in JOB_TYPES:
            assert _job_key(key).startswith(JOB_KEY_PREFIX)


# ---------------------------------------------------------------------------
# JOB_TYPES registry
# ---------------------------------------------------------------------------

class TestJobTypes:
    def test_has_five_types(self):
        assert len(JOB_TYPES) == 5

    def test_expected_keys(self):
        expected = {"text_extraction", "embedding", "summarize", "auto_tag", "word_count"}
        assert set(JOB_TYPES.keys()) == expected

    def test_each_has_label_and_description(self):
        for key, jt in JOB_TYPES.items():
            assert jt.key == key
            assert len(jt.label) > 0
            assert len(jt.description) > 0


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------

class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_returns_parsed_json_when_data_exists(self):
        data = {"status": "running", "total": 100, "processed": 50, "failed": 2}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=json.dumps(data))
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            result = await get_job_status("text_extraction")

        assert result == data
        mock_client.get.assert_called_once_with(_job_key("text_extraction"))
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_data(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            result = await get_job_status("embedding")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Redis down"))
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            result = await get_job_status("embedding")

        assert result is None
        mock_client.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# set_job_status
# ---------------------------------------------------------------------------

class TestSetJobStatus:
    @pytest.mark.asyncio
    async def test_sets_json_with_ttl(self):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            await set_job_status(
                "text_extraction", status="running", total=100, processed=50, failed=2
            )

        call_args = mock_client.set.call_args
        key = call_args[0][0]
        data = json.loads(call_args[0][1])
        ttl = call_args[1]["ex"]

        assert key == _job_key("text_extraction")
        assert data == {"status": "running", "total": 100, "processed": 50, "failed": 2}
        assert ttl == JOB_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_defaults_to_zero_counts(self):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            await set_job_status("embedding", status="completed")

        data = json.loads(mock_client.set.call_args[0][1])
        assert data["total"] == 0
        assert data["processed"] == 0
        assert data["failed"] == 0


# ---------------------------------------------------------------------------
# clear_job_status
# ---------------------------------------------------------------------------

class TestClearJobStatus:
    @pytest.mark.asyncio
    async def test_deletes_key(self):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            await clear_job_status("auto_tag")

        mock_client.delete.assert_called_once_with(_job_key("auto_tag"))


# ---------------------------------------------------------------------------
# get_all_job_statuses
# ---------------------------------------------------------------------------

class TestGetAllJobStatuses:
    @pytest.mark.asyncio
    async def test_returns_dict_for_all_job_types(self):
        data = {"status": "running", "total": 10, "processed": 5, "failed": 0}
        mock_client = AsyncMock()
        # Return data only for text_extraction, None for everything else
        async def mock_get(key):
            if key == _job_key("text_extraction"):
                return json.dumps(data)
            return None

        mock_client.get = mock_get
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            result = await get_all_job_statuses()

        assert len(result) == len(JOB_TYPES)
        assert result["text_extraction"] == data
        assert result["embedding"] is None
        assert result["summarize"] is None

    @pytest.mark.asyncio
    async def test_returns_all_none_on_redis_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Redis down"))
        mock_client.aclose = AsyncMock()

        with patch("app.services.job_queue.aioredis.from_url", return_value=mock_client):
            result = await get_all_job_statuses()

        assert all(v is None for v in result.values())
        assert set(result.keys()) == set(JOB_TYPES.keys())
