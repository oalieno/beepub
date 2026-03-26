"""Tests for app.services.job_queue — JOB_TYPES registry, run_id logic, and progress tracking."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.job_queue import (
    COMPLETED_SENTINEL,
    JOB_TYPES,
    STOPPED_SENTINEL,
    JobProgress,
    get_active_run_id,
    get_job_progress,
    init_job_progress,
    is_run_active,
    record_task_completion,
    start_job_run,
    stop_job_run,
)


def _mock_redis(**overrides) -> AsyncMock:
    """Create a mock Redis client with default stubs."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock()
    client.delete = AsyncMock()
    client.hset = AsyncMock()
    client.hgetall = AsyncMock(return_value={})
    client.aclose = AsyncMock()
    # Pipeline mock — methods are sync (only execute is async)
    pipe = MagicMock()
    pipe.set = MagicMock()
    pipe.hset = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.hgetall = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    client.pipeline = lambda: pipe
    client._pipe = pipe  # expose for assertions
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


def _patch_redis(client):
    return patch("app.services.job_queue.aioredis.from_url", return_value=client)


class TestJobTypes:
    def test_has_five_types(self):
        assert len(JOB_TYPES) == 5

    def test_expected_keys(self):
        expected = {
            "text_extraction",
            "embedding",
            "summarize",
            "auto_tag",
            "book_embedding",
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


class TestStartJobRun:
    @pytest.mark.asyncio
    async def test_returns_uuid_string(self):
        client = _mock_redis()
        with _patch_redis(client):
            run_id = await start_job_run("text_extraction")
        assert len(run_id) == 36  # UUID format
        client.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleans_up_old_active_run_progress(self):
        """When a previous active run exists, its progress hash should be deleted."""
        client = _mock_redis(get=AsyncMock(return_value=b"old-run-uuid"))
        with _patch_redis(client):
            await start_job_run("embedding")
        client.delete.assert_called_once()
        # The delete should target the old run's progress hash
        delete_key = client.delete.call_args[0][0]
        assert "old-run-uuid" in delete_key

    @pytest.mark.asyncio
    async def test_skips_cleanup_for_terminal_run(self):
        """When the previous run was already stopped/completed, don't delete progress."""
        client = _mock_redis(get=AsyncMock(return_value=STOPPED_SENTINEL.encode()))
        with _patch_redis(client):
            await start_job_run("embedding")
        client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_cleanup_when_no_previous_run(self):
        client = _mock_redis()
        with _patch_redis(client):
            await start_job_run("embedding")
        client.delete.assert_not_called()


class TestStopJobRun:
    @pytest.mark.asyncio
    async def test_returns_true_when_active(self):
        client = _mock_redis(get=AsyncMock(return_value=b"some-run-id"))
        pipe = client._pipe
        with _patch_redis(client):
            result = await stop_job_run("embedding")
        assert result is True
        pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_active(self):
        client = _mock_redis()
        with _patch_redis(client):
            result = await stop_job_run("embedding")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_already_stopped(self):
        client = _mock_redis(get=AsyncMock(return_value=STOPPED_SENTINEL.encode()))
        with _patch_redis(client):
            result = await stop_job_run("embedding")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_already_completed(self):
        client = _mock_redis(get=AsyncMock(return_value=COMPLETED_SENTINEL.encode()))
        with _patch_redis(client):
            result = await stop_job_run("embedding")
        assert result is False


class TestGetActiveRunId:
    @pytest.mark.asyncio
    async def test_returns_run_id_when_active(self):
        client = _mock_redis(get=AsyncMock(return_value=b"run-abc"))
        with _patch_redis(client):
            result = await get_active_run_id("embedding")
        assert result == "run-abc"

    @pytest.mark.asyncio
    async def test_returns_none_when_stopped(self):
        client = _mock_redis(get=AsyncMock(return_value=STOPPED_SENTINEL.encode()))
        with _patch_redis(client):
            result = await get_active_run_id("embedding")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_completed(self):
        client = _mock_redis(get=AsyncMock(return_value=COMPLETED_SENTINEL.encode()))
        with _patch_redis(client):
            result = await get_active_run_id("embedding")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_key(self):
        client = _mock_redis()
        with _patch_redis(client):
            result = await get_active_run_id("embedding")
        assert result is None


class TestIsRunActive:
    @pytest.mark.asyncio
    async def test_active_when_matching(self):
        client = _mock_redis(get=AsyncMock(return_value=b"run-123"))
        with _patch_redis(client):
            assert await is_run_active("embedding", "run-123") is True

    @pytest.mark.asyncio
    async def test_inactive_when_stopped(self):
        client = _mock_redis(get=AsyncMock(return_value=STOPPED_SENTINEL.encode()))
        with _patch_redis(client):
            assert await is_run_active("embedding", "run-123") is False

    @pytest.mark.asyncio
    async def test_inactive_when_completed(self):
        client = _mock_redis(get=AsyncMock(return_value=COMPLETED_SENTINEL.encode()))
        with _patch_redis(client):
            assert await is_run_active("embedding", "run-123") is False

    @pytest.mark.asyncio
    async def test_inactive_when_replaced(self):
        client = _mock_redis(get=AsyncMock(return_value=b"different-run-456"))
        with _patch_redis(client):
            assert await is_run_active("embedding", "run-123") is False

    @pytest.mark.asyncio
    async def test_inactive_when_key_missing(self):
        client = _mock_redis()
        with _patch_redis(client):
            assert await is_run_active("embedding", "run-123") is False


class TestInitJobProgress:
    @pytest.mark.asyncio
    async def test_creates_progress_hash(self):
        client = _mock_redis()
        with _patch_redis(client):
            await init_job_progress("embedding", "run-abc", 100)
        client.hset.assert_called_once()
        call_kwargs = client.hset.call_args
        mapping = call_kwargs[1]["mapping"]
        assert mapping["total"] == 100
        assert mapping["completed"] == 0
        assert mapping["failed"] == 0
        assert mapping["status"] == "running"
        assert "last_activity" in mapping


class TestRecordTaskCompletion:
    @pytest.mark.asyncio
    async def test_increments_completed_on_success(self):
        client = _mock_redis()
        pipe = client._pipe
        # Simulate: after increment, total=10, completed=5, failed=0 (not done yet)
        pipe.execute = AsyncMock(
            return_value=[
                1,  # hincrby result
                True,  # hset result
                {b"total": b"10", b"completed": b"5", b"failed": b"0"},
            ]
        )
        with _patch_redis(client):
            await record_task_completion("run-abc", "embedding", success=True)
        pipe.hincrby.assert_called_once()
        args = pipe.hincrby.call_args[0]
        assert args[1] == "completed"

    @pytest.mark.asyncio
    async def test_increments_failed_on_failure(self):
        client = _mock_redis()
        pipe = client._pipe
        pipe.execute = AsyncMock(
            return_value=[
                1,
                True,
                {b"total": b"10", b"completed": b"5", b"failed": b"1"},
            ]
        )
        with _patch_redis(client):
            await record_task_completion("run-abc", "embedding", success=False)
        pipe.hincrby.assert_called_once()
        args = pipe.hincrby.call_args[0]
        assert args[1] == "failed"

    @pytest.mark.asyncio
    async def test_auto_completes_when_all_done(self):
        """When completed + failed >= total, should set status to completed."""
        client = _mock_redis()
        pipe = client._pipe
        # After this increment: 9 completed + 1 failed = 10 total -> auto-complete
        pipe.execute = AsyncMock(
            return_value=[
                1,
                True,
                {b"total": b"10", b"completed": b"9", b"failed": b"1"},
            ]
        )

        # We need a second pipeline for auto-complete
        auto_pipe = MagicMock()
        auto_pipe.hset = MagicMock()
        auto_pipe.set = MagicMock()
        auto_pipe.execute = AsyncMock()

        # Track pipeline() calls: first returns pipe, second returns auto_pipe
        call_count = [0]

        def multi_pipeline():
            call_count[0] += 1
            if call_count[0] == 1:
                return pipe
            return auto_pipe

        client.pipeline = multi_pipeline

        with _patch_redis(client):
            await record_task_completion("run-abc", "embedding", success=True)

        # Auto-complete pipeline should have been executed
        auto_pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_auto_complete_when_not_done(self):
        """When completed + failed < total, should NOT set completion status."""
        client = _mock_redis()
        pipe = client._pipe
        # 5 completed + 0 failed < 10 total -> not done
        pipe.execute = AsyncMock(
            return_value=[
                1,
                True,
                {b"total": b"10", b"completed": b"5", b"failed": b"0"},
            ]
        )

        call_count = [0]

        def single_pipeline():
            call_count[0] += 1
            return pipe

        client.pipeline = single_pipeline

        with _patch_redis(client):
            await record_task_completion("run-abc", "embedding", success=True)

        # Only one pipeline call (the increment), no auto-complete
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_handles_missing_progress_hash(self):
        """If the progress hash was deleted (e.g. new run started), skip gracefully."""
        client = _mock_redis()
        pipe = client._pipe
        pipe.execute = AsyncMock(return_value=[1, True, {}])
        with _patch_redis(client):
            # Should not raise
            await record_task_completion("run-abc", "embedding", success=True)


class TestGetJobProgress:
    @pytest.mark.asyncio
    async def test_returns_progress_data(self):
        client = _mock_redis(
            hgetall=AsyncMock(
                return_value={
                    b"total": b"100",
                    b"completed": b"42",
                    b"failed": b"3",
                    b"status": b"running",
                    b"last_activity": b"1711234567",
                }
            )
        )
        with _patch_redis(client):
            result = await get_job_progress("run-abc")
        assert isinstance(result, JobProgress)
        assert result.total == 100
        assert result.completed == 42
        assert result.failed == 3
        assert result.status == "running"
        assert result.last_activity == 1711234567.0

    @pytest.mark.asyncio
    async def test_returns_none_when_no_data(self):
        client = _mock_redis()
        with _patch_redis(client):
            result = await get_job_progress("nonexistent-run")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_missing_last_activity(self):
        client = _mock_redis(
            hgetall=AsyncMock(
                return_value={
                    b"total": b"10",
                    b"completed": b"0",
                    b"failed": b"0",
                    b"status": b"running",
                }
            )
        )
        with _patch_redis(client):
            result = await get_job_progress("run-abc")
        assert result is not None
        assert result.last_activity is None
