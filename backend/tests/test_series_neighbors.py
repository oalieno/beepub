"""Tests for series-neighbors schemas."""

import uuid

from app.schemas.book import SeriesBookBrief, SeriesNeighborsOut, SeriesProgress

# ---------------------------------------------------------------------------
# SeriesBookBrief
# ---------------------------------------------------------------------------


class TestSeriesBookBrief:
    def test_all_fields(self):
        uid = uuid.uuid4()
        brief = SeriesBookBrief(
            id=uid,
            title="Book Two",
            authors=["Author A"],
            cover_path="/covers/2.jpg",
            series_index=2.0,
        )
        assert brief.id == uid
        assert brief.title == "Book Two"
        assert brief.authors == ["Author A"]
        assert brief.cover_path == "/covers/2.jpg"
        assert brief.series_index == 2.0

    def test_nullable_fields(self):
        brief = SeriesBookBrief(
            id=uuid.uuid4(),
            title=None,
            authors=None,
            cover_path=None,
            series_index=None,
        )
        assert brief.title is None
        assert brief.authors is None
        assert brief.cover_path is None
        assert brief.series_index is None

    def test_float_series_index(self):
        brief = SeriesBookBrief(
            id=uuid.uuid4(),
            title="Novella 1.5",
            authors=None,
            cover_path=None,
            series_index=1.5,
        )
        assert brief.series_index == 1.5

    def test_serialization(self):
        uid = uuid.uuid4()
        brief = SeriesBookBrief(
            id=uid,
            title="Test",
            authors=["A"],
            cover_path=None,
            series_index=3.0,
        )
        data = brief.model_dump()
        assert set(data.keys()) == {
            "id",
            "title",
            "authors",
            "cover_path",
            "series_index",
        }
        assert data["id"] == uid


# ---------------------------------------------------------------------------
# SeriesProgress
# ---------------------------------------------------------------------------


class TestSeriesProgress:
    def test_basic(self):
        progress = SeriesProgress(total_in_library=5, max_series_index=6.0, read_count=3)
        assert progress.total_in_library == 5
        assert progress.max_series_index == 6.0
        assert progress.read_count == 3

    def test_max_series_index_supports_gaps_and_fractional_indices(self):
        progress = SeriesProgress(
            total_in_library=11,
            max_series_index=12.5,
            read_count=4,
        )
        assert progress.total_in_library == 11
        assert progress.max_series_index == 12.5

    def test_zero_counts(self):
        progress = SeriesProgress(total_in_library=0, read_count=0)
        assert progress.total_in_library == 0
        assert progress.max_series_index is None
        assert progress.read_count == 0

    def test_all_read(self):
        progress = SeriesProgress(total_in_library=3, read_count=3)
        assert progress.read_count == progress.total_in_library


# ---------------------------------------------------------------------------
# SeriesNeighborsOut
# ---------------------------------------------------------------------------


class TestSeriesNeighborsOut:
    def test_empty_response(self):
        """Book with no series returns all-null response."""
        out = SeriesNeighborsOut()
        assert out.series_name is None
        assert out.current_index is None
        assert out.next is None
        assert out.previous is None
        assert out.progress is None

    def test_with_next_only(self):
        next_book = SeriesBookBrief(
            id=uuid.uuid4(),
            title="Book 2",
            authors=["Author"],
            cover_path=None,
            series_index=2.0,
        )
        out = SeriesNeighborsOut(
            series_name="My Series",
            current_index=1.0,
            next=next_book,
            previous=None,
            progress=SeriesProgress(total_in_library=3, read_count=1),
        )
        assert out.series_name == "My Series"
        assert out.current_index == 1.0
        assert out.next is not None
        assert out.next.title == "Book 2"
        assert out.previous is None
        assert out.progress is not None
        assert out.progress.total_in_library == 3

    def test_with_both_neighbors(self):
        prev_book = SeriesBookBrief(
            id=uuid.uuid4(),
            title="Book 1",
            authors=None,
            cover_path=None,
            series_index=1.0,
        )
        next_book = SeriesBookBrief(
            id=uuid.uuid4(),
            title="Book 3",
            authors=None,
            cover_path=None,
            series_index=3.0,
        )
        out = SeriesNeighborsOut(
            series_name="Trilogy",
            current_index=2.0,
            next=next_book,
            previous=prev_book,
            progress=SeriesProgress(total_in_library=3, read_count=2),
        )
        assert out.previous is not None
        assert out.previous.series_index == 1.0
        assert out.next is not None
        assert out.next.series_index == 3.0

    def test_last_book_in_series(self):
        """Last book: has previous but no next."""
        prev_book = SeriesBookBrief(
            id=uuid.uuid4(),
            title="Book 2",
            authors=None,
            cover_path=None,
            series_index=2.0,
        )
        out = SeriesNeighborsOut(
            series_name="Trilogy",
            current_index=3.0,
            next=None,
            previous=prev_book,
            progress=SeriesProgress(total_in_library=3, read_count=3),
        )
        assert out.next is None
        assert out.previous is not None
        assert out.progress is not None
        assert out.progress.read_count == out.progress.total_in_library

    def test_float_index_gap(self):
        """Series with non-integer indices (e.g., 1.0, 1.5, 2.0)."""
        next_book = SeriesBookBrief(
            id=uuid.uuid4(),
            title="Novella",
            authors=None,
            cover_path=None,
            series_index=1.5,
        )
        out = SeriesNeighborsOut(
            series_name="Series",
            current_index=1.0,
            next=next_book,
            progress=SeriesProgress(total_in_library=3, read_count=0),
        )
        assert out.next is not None
        assert out.next.series_index == 1.5

    def test_serialization_nested(self):
        """Full serialization round-trip with nested models."""
        out = SeriesNeighborsOut(
            series_name="Test",
            current_index=1.0,
            next=SeriesBookBrief(
                id=uuid.uuid4(),
                title="Next",
                authors=["A"],
                cover_path="/c.jpg",
                series_index=2.0,
            ),
            previous=None,
            progress=SeriesProgress(total_in_library=2, read_count=1),
        )
        data = out.model_dump()
        assert data["series_name"] == "Test"
        assert data["next"]["title"] == "Next"
        assert data["next"]["series_index"] == 2.0
        assert data["previous"] is None
        assert data["progress"]["total_in_library"] == 2
