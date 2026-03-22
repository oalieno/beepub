"""Tests for keyword search schemas and endpoint logic."""

from app.routers.search import KeywordSearchResponse, KeywordSearchResult

# ---------------------------------------------------------------------------
# KeywordSearchResult schema
# ---------------------------------------------------------------------------


class TestKeywordSearchResult:
    def test_all_fields(self):
        result = KeywordSearchResult(
            book_id="abc-123",
            book_title="My Book",
            book_author="Author Name",
            passage="some matching text here",
            spine_index=3,
            char_offset_start=100,
            char_offset_end=200,
        )
        assert result.book_id == "abc-123"
        assert result.book_title == "My Book"
        assert result.book_author == "Author Name"
        assert result.passage == "some matching text here"
        assert result.spine_index == 3
        assert result.char_offset_start == 100
        assert result.char_offset_end == 200

    def test_nullable_author(self):
        result = KeywordSearchResult(
            book_id="abc",
            book_title="Untitled",
            book_author=None,
            passage="text",
            spine_index=0,
            char_offset_start=0,
            char_offset_end=10,
        )
        assert result.book_author is None

    def test_serialization(self):
        result = KeywordSearchResult(
            book_id="id-1",
            book_title="Title",
            book_author="Auth",
            passage="passage text",
            spine_index=1,
            char_offset_start=0,
            char_offset_end=50,
        )
        data = result.model_dump()
        assert set(data.keys()) == {
            "book_id",
            "book_title",
            "book_author",
            "passage",
            "spine_index",
            "char_offset_start",
            "char_offset_end",
        }


# ---------------------------------------------------------------------------
# KeywordSearchResponse schema
# ---------------------------------------------------------------------------


class TestKeywordSearchResponse:
    def test_empty_results(self):
        resp = KeywordSearchResponse(results=[], query="test", total=0)
        assert resp.results == []
        assert resp.query == "test"
        assert resp.total == 0

    def test_with_results(self):
        items = [
            KeywordSearchResult(
                book_id=f"id-{i}",
                book_title=f"Book {i}",
                book_author=None,
                passage=f"passage {i}",
                spine_index=i,
                char_offset_start=0,
                char_offset_end=50,
            )
            for i in range(3)
        ]
        resp = KeywordSearchResponse(results=items, query="hello", total=10)
        assert len(resp.results) == 3
        assert resp.total == 10
        assert resp.query == "hello"

    def test_total_can_exceed_results_length(self):
        """Total reflects DB count, results are limited."""
        items = [
            KeywordSearchResult(
                book_id="id-0",
                book_title="Book",
                book_author=None,
                passage="text",
                spine_index=0,
                char_offset_start=0,
                char_offset_end=10,
            )
        ]
        resp = KeywordSearchResponse(results=items, query="q", total=500)
        assert len(resp.results) == 1
        assert resp.total == 500

    def test_serialization_matches_api_contract(self):
        resp = KeywordSearchResponse(results=[], query="test", total=0)
        data = resp.model_dump()
        assert set(data.keys()) == {"results", "query", "total"}
