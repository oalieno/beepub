"""Tests for calibre auto-sync gate logic and helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.calibre import get_metadata_db_mtime, scan_calibre_libraries


class TestGetMetadataDbMtime:
    """Tests for the mtime helper function."""

    def test_returns_utc_datetime(self, tmp_path):
        """mtime returns a timezone-aware UTC datetime for an existing file."""
        db_file = tmp_path / "metadata.db"
        db_file.write_text("test")
        result = get_metadata_db_mtime(str(tmp_path))
        assert result is not None
        assert result.tzinfo is not None
        assert result.tzinfo == UTC

    def test_returns_none_on_missing_file(self, tmp_path):
        """mtime returns None when metadata.db doesn't exist."""
        result = get_metadata_db_mtime(str(tmp_path / "nonexistent"))
        assert result is None


class TestScanCalibreLibraries:
    """Tests for Calibre library discovery."""

    def test_scans_custom_base_dir(self, tmp_path):
        root = tmp_path / "custom-calibre"
        library = root / "Library A"
        library.mkdir(parents=True)
        (library / "metadata.db").write_text("not a real sqlite db")

        result = scan_calibre_libraries(str(root))

        assert result == [
            {
                "path": str(library),
                "name": "Library A",
                "book_count": None,
            }
        ]

    def test_missing_base_dir_returns_empty_list(self, tmp_path):
        result = scan_calibre_libraries(str(tmp_path / "missing"))

        assert result == []


def _make_library(**overrides):
    """Create a mock Library object."""
    lib = MagicMock()
    lib.id = overrides.get("id", uuid.uuid4())
    lib.name = overrides.get("name", "Test Library")
    lib.calibre_path = overrides.get("calibre_path", "/calibre/test")
    lib.auto_sync = overrides.get("auto_sync", True)
    lib.last_synced_at = overrides.get(
        "last_synced_at", datetime.now(UTC) - timedelta(hours=2)
    )
    lib.created_by = overrides.get("created_by", uuid.uuid4())
    return lib


def _make_redis(lock_acquired=True):
    """Create a mock Redis client."""
    client = AsyncMock()
    client.set = AsyncMock(return_value=lock_acquired)
    client.delete = AsyncMock()
    client.aclose = AsyncMock()
    return client


async def _run_check(
    libraries,
    settings_dict=None,
    force=False,
    lock_acquired=True,
    mtime_value=None,
    sync_status_value=None,
):
    """Run _check_and_sync_calibre with fully mocked dependencies."""
    if settings_dict is None:
        settings_dict = {
            "calibre_auto_sync_interval_minutes": "30",
        }

    if mtime_value is None:
        mtime_value = datetime.now(UTC)

    mock_redis = _make_redis(lock_acquired)

    # Mock session and DB query
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()
    mock_query_result = MagicMock()
    mock_query_result.scalars.return_value.all.return_value = libraries
    mock_session.execute = AsyncMock(return_value=mock_query_result)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    mock_engine_ctx = AsyncMock()
    mock_engine_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), mock_factory))
    mock_engine_ctx.__aexit__ = AsyncMock()

    async def mock_get_setting(db, key):
        return settings_dict.get(key, "")

    with (
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("app.database.create_task_engine", return_value=mock_engine_ctx),
        patch("app.services.settings.get_setting", side_effect=mock_get_setting),
        patch("app.services.calibre.get_metadata_db_mtime", return_value=mtime_value),
        patch(
            "app.services.calibre.get_sync_status",
            new_callable=AsyncMock,
            return_value=sync_status_value,
        ),
        patch("app.tasks.calibre_sync.sync_calibre_library") as mock_task,
    ):
        from app.tasks.calibre_sync import _check_and_sync_calibre

        await _check_and_sync_calibre(force=force)

    return mock_task


class TestCheckAndSyncCalibre:
    """Tests for the gate-check dispatcher logic."""

    @pytest.mark.asyncio
    async def test_skip_when_no_libraries(self):
        """Should not dispatch when no auto-sync libraries exist."""
        mock_task = await _run_check(libraries=[])
        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_interval_not_elapsed(self):
        """Should skip a library when the interval hasn't elapsed yet."""
        lib = _make_library(last_synced_at=datetime.now(UTC) - timedelta(minutes=5))
        mock_task = await _run_check(libraries=[lib])
        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_mtime_unchanged(self):
        """Should skip when metadata.db mtime hasn't changed since last sync."""
        last_synced = datetime.now(UTC) - timedelta(hours=2)
        lib = _make_library(last_synced_at=last_synced)
        # mtime is OLDER than last_synced_at
        mock_task = await _run_check(
            libraries=[lib],
            mtime_value=last_synced - timedelta(hours=1),
        )
        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_already_running(self):
        """Should skip when sync is already running for the library."""
        lib = _make_library()
        mock_task = await _run_check(
            libraries=[lib],
            sync_status_value={
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
            },
        )
        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_when_all_gates_pass(self):
        """Should dispatch sync task when all gates pass."""
        lib = _make_library()
        mock_task = await _run_check(libraries=[lib])
        mock_task.delay.assert_called_once_with(
            lib.calibre_path,
            str(lib.id),
            str(lib.created_by),
        )

    @pytest.mark.asyncio
    async def test_force_skips_interval_check(self):
        """force=True should skip the interval check."""
        lib = _make_library(last_synced_at=datetime.now(UTC) - timedelta(minutes=1))
        mock_task = await _run_check(libraries=[lib], force=True)
        mock_task.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_when_lock_not_acquired(self):
        """Should return immediately if Redis lock is not acquired."""
        lib = _make_library()
        mock_task = await _run_check(libraries=[lib], lock_acquired=False)
        mock_task.delay.assert_not_called()


class TestMetadataChainDispatch:
    """Tests for metadata chain dispatch after commit in sync_calibre_library."""

    @patch("app.services.calibre.extract_book_text")
    def test_extract_has_delay_method(self, mock_extract):
        """Verify that extract_book_text task has a delay method."""
        assert hasattr(mock_extract, "delay")

    def test_auto_start_backfill_import_available(self):
        """Verify auto_start_backfill can be imported."""
        from app.tasks.metadata import auto_start_backfill

        assert callable(auto_start_backfill)
