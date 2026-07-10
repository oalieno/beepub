import uuid
from datetime import date, datetime

from pydantic import BaseModel


class RatingUpdate(BaseModel):
    rating: float | None = None  # 0.5-5 in 0.5 steps, or null


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class ProgressUpdate(BaseModel):
    cfi: str
    # None = the reader's CFI moved before the canonical (locations-based)
    # percentage was known; the previously stored percentage is kept.
    percentage: float | None = None
    current_page: int | None = None
    font_size: int | None = None
    section_index: int | None = None
    section_page: int | None = None
    section_page_counts: list[int] | None = None
    total_pages: int | None = None
    track_activity: bool = True


class KosyncMarkerOut(BaseModel):
    """E-reader position bridged from kosync, newer than the stored CFI.

    Written by the kosync bridge; the web PUT /progress rebuilds the whole
    progress dict, so the marker disappears once the user reads on the web.
    """

    percentage: float | None = None
    device: str | None = None
    synced_at: str | None = None


class ProgressOut(BaseModel):
    cfi: str | None = None
    percentage: float | None = None
    current_page: int | None = None
    font_size: int | None = None
    section_index: int | None = None
    section_page: int | None = None
    section_page_counts: list[int] | None = None
    total_pages: int | None = None
    last_read_at: str | None = None
    kosync: KosyncMarkerOut | None = None


class HighlightCreate(BaseModel):
    cfi_range: str
    text: str
    color: str = "yellow"
    note: str | None = None


class HighlightUpdate(BaseModel):
    color: str | None = None
    note: str | None = None


class HighlightOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    cfi_range: str
    text: str
    color: str
    note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReadingStatusUpdate(BaseModel):
    reading_status: str | None = (
        None  # want_to_read, currently_reading, read, did_not_finish
    )
    started_at: date | None = None
    finished_at: date | None = None


class NotesUpdate(BaseModel):
    notes: str | None = None  # markdown


class ReadingActivityOut(BaseModel):
    date: date
    seconds: int

    model_config = {"from_attributes": True}


class ReadingStatsOut(BaseModel):
    current_streak: int
    longest_streak: int
    today_seconds: int
    goal_seconds: int | None


class ReadingGoalUpdate(BaseModel):
    goal_seconds: int | None = None  # null to remove goal

    model_config = {
        "json_schema_extra": {
            "examples": [{"goal_seconds": 1800}],
        }
    }


class InteractionOut(BaseModel):
    rating: float | None
    is_favorite: bool
    reading_progress: dict | None
    reading_status: str | None
    started_at: date | None
    finished_at: date | None
    notes: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaginatedHighlights(BaseModel):
    items: list[HighlightOut]
    total: int
