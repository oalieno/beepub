"""Tests for app.tasks.bulk_jobs — task execution."""

from unittest.mock import MagicMock, patch

from app.tasks.bulk_jobs import _execute_book_task


class TestExecuteBookTask:
    """Verify _execute_book_task calls the correct inner async functions."""

    @patch("app.celeryapp.run_async")
    def test_text_extraction(self, mock_run_async):
        with patch(
            "app.tasks.text_extract._run_text_extract", new_callable=MagicMock
        ) as mock_fn:
            mock_fn.return_value = "coro"
            _execute_book_task("text_extraction", "book-123")
            mock_run_async.assert_called_once()

    @patch("app.celeryapp.run_async")
    def test_embedding_runs_extract_then_embed(self, mock_run_async):
        with (
            patch(
                "app.tasks.text_extract._run_text_extract", new_callable=MagicMock
            ) as mock_extract,
            patch(
                "app.tasks.embed._run_embed_book", new_callable=MagicMock
            ) as mock_embed,
        ):
            mock_extract.return_value = "coro1"
            mock_embed.return_value = "coro2"
            _execute_book_task("embedding", "book-456")
            assert mock_run_async.call_count == 2

    @patch("app.celeryapp.run_async")
    def test_summarize_runs_extract_then_summarize(self, mock_run_async):
        with (
            patch(
                "app.tasks.text_extract._run_text_extract", new_callable=MagicMock
            ) as mock_extract,
            patch(
                "app.tasks.summarize._run_summarize_chunks", new_callable=MagicMock
            ) as mock_summarize,
        ):
            mock_extract.return_value = "coro1"
            mock_summarize.return_value = "coro2"
            _execute_book_task("summarize", "book-789")
            assert mock_run_async.call_count == 2

    @patch("app.celeryapp.run_async")
    def test_auto_tag(self, mock_run_async):
        with patch(
            "app.tasks.auto_tag._run_auto_tag_book", new_callable=MagicMock
        ) as mock_fn:
            mock_fn.return_value = "coro"
            _execute_book_task("auto_tag", "book-aaa")
            mock_run_async.assert_called_once()

    @patch("app.celeryapp.run_async")
    def test_book_embedding(self, mock_run_async):
        with patch(
            "app.tasks.embed._run_embed_book_summary", new_callable=MagicMock
        ) as mock_fn:
            mock_fn.return_value = "coro"
            _execute_book_task("book_embedding", "book-ccc")
            mock_run_async.assert_called_once()

    @patch("app.celeryapp.run_async")
    def test_unknown_type_does_nothing(self, mock_run_async):
        _execute_book_task("nonexistent_job", "book-xxx")
        mock_run_async.assert_not_called()
