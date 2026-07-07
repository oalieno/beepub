"""Tests for app.config — SECRET_KEY auto-generation and persistence."""

import pytest

from app.config import Settings

DB_URL = "postgresql+asyncpg://test:test@localhost:5432/test"


def make_settings(tmp_path, **overrides):
    kwargs = {
        "database_url": DB_URL,
        "secret_key": "",
        "secret_key_file": str(tmp_path / "secret_key"),
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


class TestSecretKeyResolution:
    def test_explicit_key_wins(self, tmp_path):
        s = make_settings(tmp_path, secret_key="explicit")
        assert s.secret_key == "explicit"
        assert not (tmp_path / "secret_key").exists()

    def test_generates_and_persists_when_unset(self, tmp_path):
        s = make_settings(tmp_path)
        key_file = tmp_path / "secret_key"
        assert len(s.secret_key) == 64  # token_hex(32)
        assert key_file.read_text() == s.secret_key
        assert key_file.stat().st_mode & 0o777 == 0o600

    def test_reuses_persisted_key(self, tmp_path):
        first = make_settings(tmp_path)
        second = make_settings(tmp_path)
        assert second.secret_key == first.secret_key

    def test_regenerates_when_file_empty(self, tmp_path):
        (tmp_path / "secret_key").write_text("  \n")
        s = make_settings(tmp_path)
        assert len(s.secret_key) == 64

    def test_creates_missing_parent_dirs(self, tmp_path):
        s = make_settings(
            tmp_path, secret_key_file=str(tmp_path / "nested" / "dir" / "key")
        )
        assert len(s.secret_key) == 64

    def test_clear_error_when_unwritable(self, tmp_path):
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        ro_dir.chmod(0o500)
        try:
            with pytest.raises(RuntimeError, match="set SECRET_KEY explicitly"):
                make_settings(tmp_path, secret_key_file=str(ro_dir / "key"))
        finally:
            ro_dir.chmod(0o700)
