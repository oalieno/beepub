"""Tests for app.tasks.bulk_jobs — fat task dispatch and execution."""

from unittest.mock import patch

from app.tasks.bulk_jobs import _dispatch_single, _execute_book_task


class TestDispatchSingle:
    """Verify _dispatch_single dispatches run_book_job.delay() with correct args."""

    @patch("app.tasks.bulk_jobs.run_book_job")
    def test_dispatches_run_book_job(self, mock_task):
        _dispatch_single("text_extraction", "book-123", "run-abc")
        mock_task.delay.assert_called_once_with(
            "text_extraction", "book-123", "run-abc"
        )

    @patch("app.tasks.bulk_jobs.run_book_job")
    def test_unknown_type_still_dispatches(self, mock_task):
        # Unknown types are handled in _execute_book_task, not _dispatch_single
        _dispatch_single("nonexistent_job", "book-xxx", "run-abc")
        mock_task.delay.assert_called_once_with(
            "nonexistent_job", "book-xxx", "run-abc"
        )


class TestExecuteBookTask:
    """Verify _execute_book_task calls the correct inner async functions."""

    @patch("app.celeryapp.run_async")
    def test_text_extraction(self, mock_run_async):
        with patch("app.tasks.text_extract._run_text_extract") as mock_fn:
            mock_fn.return_value = "coro"
            _execute_book_task("text_extraction", "book-123")
            mock_run_async.assert_called_once()

    @patch("app.celeryapp.run_async")
    def test_embedding_runs_extract_then_embed(self, mock_run_async):
        with (
            patch("app.tasks.text_extract._run_text_extract") as mock_extract,
            patch("app.tasks.embed._run_embed_book") as mock_embed,
        ):
            mock_extract.return_value = "coro1"
            mock_embed.return_value = "coro2"
            _execute_book_task("embedding", "book-456")
            assert mock_run_async.call_count == 2

    @patch("app.celeryapp.run_async")
    def test_summarize_runs_extract_then_summarize(self, mock_run_async):
        with (
            patch("app.tasks.text_extract._run_text_extract") as mock_extract,
            patch("app.tasks.summarize._run_summarize_chunks") as mock_summarize,
        ):
            mock_extract.return_value = "coro1"
            mock_summarize.return_value = "coro2"
            _execute_book_task("summarize", "book-789")
            assert mock_run_async.call_count == 2

    @patch("app.celeryapp.run_async")
    def test_auto_tag(self, mock_run_async):
        with patch("app.tasks.auto_tag._run_auto_tag_book") as mock_fn:
            mock_fn.return_value = "coro"
            _execute_book_task("auto_tag", "book-aaa")
            mock_run_async.assert_called_once()

    @patch("app.celeryapp.run_async")
    def test_book_embedding(self, mock_run_async):
        with patch("app.tasks.embed._run_embed_book_summary") as mock_fn:
            mock_fn.return_value = "coro"
            _execute_book_task("book_embedding", "book-ccc")
            mock_run_async.assert_called_once()

    @patch("app.celeryapp.run_async")
    def test_unknown_type_does_nothing(self, mock_run_async):
        _execute_book_task("nonexistent_job", "book-xxx")
        mock_run_async.assert_not_called()
