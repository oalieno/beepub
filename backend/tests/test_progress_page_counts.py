"""A chapter the reader has not measured has no page count; clients have
sent that as null. The position must still be accepted."""

from app.schemas.reading import ProgressUpdate, SyncProgressIn


def test_sync_progress_accepts_unmeasured_chapters():
    progress = SyncProgressIn(
        cfi="epubcfi(/6/4!/4/2/1:0)",
        last_read_at="2026-10-07T00:00:00Z",
        section_page_counts=[3, None, 2.0, -1, float("nan"), "x", True],
    )
    assert progress.section_page_counts == [3, 0, 2, 0, 0, 0, 0]


def test_progress_update_accepts_unmeasured_chapters():
    assert ProgressUpdate(
        cfi="epubcfi(/6/4!/4/2/1:0)", section_page_counts=[None, 5]
    ).section_page_counts == [0, 5]
    assert ProgressUpdate(cfi="epubcfi(/6/4!/4/2/1:0)").section_page_counts is None
