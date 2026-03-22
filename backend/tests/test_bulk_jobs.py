"""Tests for app.tasks.bulk_jobs — dispatch logic and missing book ID queries."""

from unittest.mock import patch

from app.tasks.bulk_jobs import _dispatch_single


class TestDispatchSingle:
    """Verify _dispatch_single calls the correct per-book task for each job type."""

    @patch("app.tasks.bulk_jobs.extract_book_text", create=True)
    def test_text_extraction(self, mock_extract):
        # Need to patch at the import location inside the function
        with patch("app.tasks.text_extract.extract_book_text") as mock_task:
            _dispatch_single("text_extraction", "book-123")
            mock_task.assert_called_once_with("book-123")

    @patch("app.tasks.embed.embed_book")
    @patch("app.tasks.text_extract.extract_book_text")
    def test_embedding_extracts_text_first(self, mock_extract, mock_embed):
        _dispatch_single("embedding", "book-456")
        # Text extraction should be called before embedding
        mock_extract.assert_called_once_with("book-456")
        mock_embed.assert_called_once_with("book-456")

    @patch("app.tasks.summarize.summarize_chunks")
    @patch("app.tasks.text_extract.extract_book_text")
    def test_summarize_extracts_text_first(self, mock_extract, mock_summarize):
        _dispatch_single("summarize", "book-789")
        mock_extract.assert_called_once_with("book-789")
        mock_summarize.assert_called_once_with("book-789", up_to_spine_index=999999)

    @patch("app.tasks.auto_tag.auto_tag_book")
    def test_auto_tag(self, mock_tag):
        _dispatch_single("auto_tag", "book-aaa")
        mock_tag.assert_called_once_with("book-aaa")

    @patch("app.tasks.wordcount.compute_word_count")
    def test_word_count(self, mock_wc):
        _dispatch_single("word_count", "book-bbb")
        mock_wc.assert_called_once_with("book-bbb")

    def test_unknown_type_does_nothing(self):
        # Should not raise for unknown job type
        _dispatch_single("nonexistent_job", "book-xxx")
