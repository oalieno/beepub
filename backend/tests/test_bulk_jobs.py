"""Tests for app.tasks.bulk_jobs — dispatch logic with run_id guard."""

from unittest.mock import MagicMock, patch

from app.tasks.bulk_jobs import _dispatch_single


class TestDispatchSingle:
    """Verify _dispatch_single dispatches a chain with run_id guard + per-book task."""

    @patch("app.tasks.text_extract.extract_book_text")
    @patch("app.tasks.bulk_jobs.check_run_id")
    @patch("celery.chain")
    def test_text_extraction(self, mock_chain_cls, mock_guard, mock_task):
        mock_chain = MagicMock()
        mock_chain_cls.return_value = mock_chain
        _dispatch_single("text_extraction", "book-123", "run-abc")
        mock_chain_cls.assert_called_once()
        mock_chain.delay.assert_called_once()

    @patch("app.tasks.embed.embed_book")
    @patch("app.tasks.text_extract.extract_book_text")
    @patch("app.tasks.bulk_jobs.check_run_id")
    @patch("celery.chain")
    def test_embedding_chains_guard_extract_embed(
        self, mock_chain_cls, mock_guard, mock_extract, mock_embed
    ):
        mock_chain = MagicMock()
        mock_chain_cls.return_value = mock_chain
        _dispatch_single("embedding", "book-456", "run-abc")
        # Should chain 3 tasks: guard, extract, embed
        args = mock_chain_cls.call_args[0]
        assert len(args) == 3
        mock_chain.delay.assert_called_once()

    @patch("app.tasks.summarize.summarize_chunks")
    @patch("app.tasks.text_extract.extract_book_text")
    @patch("app.tasks.bulk_jobs.check_run_id")
    @patch("celery.chain")
    def test_summarize_chains_guard_extract_summarize(
        self, mock_chain_cls, mock_guard, mock_extract, mock_summarize
    ):
        mock_chain = MagicMock()
        mock_chain_cls.return_value = mock_chain
        _dispatch_single("summarize", "book-789", "run-abc")
        args = mock_chain_cls.call_args[0]
        assert len(args) == 3
        mock_chain.delay.assert_called_once()

    @patch("app.tasks.auto_tag.auto_tag_book")
    @patch("app.tasks.bulk_jobs.check_run_id")
    @patch("celery.chain")
    def test_auto_tag(self, mock_chain_cls, mock_guard, mock_tag):
        mock_chain = MagicMock()
        mock_chain_cls.return_value = mock_chain
        _dispatch_single("auto_tag", "book-aaa", "run-abc")
        mock_chain.delay.assert_called_once()

    @patch("app.tasks.wordcount.compute_word_count")
    @patch("app.tasks.bulk_jobs.check_run_id")
    @patch("celery.chain")
    def test_word_count(self, mock_chain_cls, mock_guard, mock_wc):
        mock_chain = MagicMock()
        mock_chain_cls.return_value = mock_chain
        _dispatch_single("word_count", "book-bbb", "run-abc")
        mock_chain.delay.assert_called_once()

    def test_unknown_type_does_nothing(self):
        # Should not raise for unknown job type
        _dispatch_single("nonexistent_job", "book-xxx", "run-abc")
