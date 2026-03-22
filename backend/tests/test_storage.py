"""Tests for app.services.storage — path generation, file save/delete."""

import uuid
from unittest.mock import AsyncMock, mock_open, patch

import pytest

from app.services.storage import (
    delete_file,
    get_book_path,
    get_cover_path,
    get_illustration_path,
    save_upload_file,
)

# ---------------------------------------------------------------------------
# get_book_path
# ---------------------------------------------------------------------------


class TestGetBookPath:
    def test_epub_extension(self):
        book_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = get_book_path(book_id, "my-book.epub")
        assert result.endswith(f"/{book_id}.epub")

    def test_pdf_extension(self):
        book_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = get_book_path(book_id, "document.pdf")
        assert result.endswith(f"/{book_id}.pdf")

    def test_preserves_extension_only(self):
        """Original filename is discarded; only extension is kept."""
        book_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        result = get_book_path(book_id, "Some Long Title (2024).epub")
        assert "Some Long Title" not in result
        assert str(book_id) in result

    def test_no_extension(self):
        book_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = get_book_path(book_id, "noext")
        assert result.endswith(str(book_id))

    def test_uses_books_dir_from_settings(self):
        book_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        with patch("app.services.storage.settings") as mock_settings:
            mock_settings.books_dir = "/custom/books"
            result = get_book_path(book_id, "file.epub")
        assert result.startswith("/custom/books/")


# ---------------------------------------------------------------------------
# get_cover_path
# ---------------------------------------------------------------------------


class TestGetCoverPath:
    def test_returns_jpg_with_book_id(self):
        book_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = get_cover_path(book_id)
        assert result.endswith(f"/{book_id}.jpg")

    def test_uses_covers_dir_from_settings(self):
        book_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        with patch("app.services.storage.settings") as mock_settings:
            mock_settings.covers_dir = "/custom/covers"
            result = get_cover_path(book_id)
        assert result.startswith("/custom/covers/")


# ---------------------------------------------------------------------------
# get_illustration_path
# ---------------------------------------------------------------------------


class TestGetIllustrationPath:
    def test_returns_png_with_illustration_id(self):
        illus_id = uuid.UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        result = get_illustration_path(illus_id)
        assert result.endswith(f"/{illus_id}.png")

    def test_uses_illustrations_dir_from_settings(self):
        illus_id = uuid.UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        with patch("app.services.storage.settings") as mock_settings:
            mock_settings.illustrations_dir = "/custom/illustrations"
            result = get_illustration_path(illus_id)
        assert result.startswith("/custom/illustrations/")


# ---------------------------------------------------------------------------
# save_upload_file
# ---------------------------------------------------------------------------


class TestSaveUploadFile:
    @pytest.mark.asyncio
    async def test_writes_content_and_returns_size(self):
        content = b"hello world epub content"
        upload = AsyncMock(spec=["read"])
        upload.read = AsyncMock(side_effect=[content, b""])

        m = mock_open()
        with (
            patch("app.services.storage.os.makedirs") as mock_makedirs,
            patch("builtins.open", m),
        ):
            size = await save_upload_file(upload, "/data/books/test.epub")

        mock_makedirs.assert_called_once_with("/data/books", exist_ok=True)
        m.assert_called_once_with("/data/books/test.epub", "wb")
        m().write.assert_called_once_with(content)
        assert size == len(content)

    @pytest.mark.asyncio
    async def test_handles_multiple_chunks(self):
        chunk1 = b"a" * 1024
        chunk2 = b"b" * 512
        upload = AsyncMock(spec=["read"])
        upload.read = AsyncMock(side_effect=[chunk1, chunk2, b""])

        m = mock_open()
        with (
            patch("app.services.storage.os.makedirs"),
            patch("builtins.open", m),
        ):
            size = await save_upload_file(upload, "/data/books/test.epub")

        assert size == 1024 + 512
        assert m().write.call_count == 2

    @pytest.mark.asyncio
    async def test_creates_missing_parent_directories(self):
        upload = AsyncMock(spec=["read"])
        upload.read = AsyncMock(side_effect=[b""])

        m = mock_open()
        with (
            patch("app.services.storage.os.makedirs") as mock_makedirs,
            patch("builtins.open", m),
        ):
            await save_upload_file(upload, "/data/deep/nested/dir/file.epub")

        mock_makedirs.assert_called_once_with("/data/deep/nested/dir", exist_ok=True)

    @pytest.mark.asyncio
    async def test_empty_file_returns_zero(self):
        upload = AsyncMock(spec=["read"])
        upload.read = AsyncMock(side_effect=[b""])

        m = mock_open()
        with (
            patch("app.services.storage.os.makedirs"),
            patch("builtins.open", m),
        ):
            size = await save_upload_file(upload, "/data/books/empty.epub")

        assert size == 0


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    def test_removes_file(self):
        with patch("app.services.storage.os.remove") as mock_remove:
            delete_file("/data/books/test.epub")

        mock_remove.assert_called_once_with("/data/books/test.epub")

    def test_ignores_file_not_found(self):
        with patch("app.services.storage.os.remove", side_effect=FileNotFoundError):
            # Should not raise
            delete_file("/data/books/nonexistent.epub")

    def test_propagates_other_os_errors(self):
        with patch(
            "app.services.storage.os.remove", side_effect=PermissionError("denied")
        ):
            with pytest.raises(PermissionError):
                delete_file("/data/books/locked.epub")
