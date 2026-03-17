import uuid
from datetime import date, datetime

from pydantic import BaseModel


class RatingUpdate(BaseModel):
    rating: int | None = None  # 1-5 or null


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class ProgressUpdate(BaseModel):
    cfi: str
    percentage: float
    current_page: int | None = None
    font_size: int | None = None
    section_index: int | None = None
    section_page: int | None = None
    section_page_counts: list[int] | None = None
    total_pages: int | None = None
    track_activity: bool = True


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


class InteractionOut(BaseModel):
    rating: int | None
    is_favorite: bool
    reading_progress: dict | None
    reading_status: str | None
    started_at: date | None
    finished_at: date | None
    notes: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchInteractionItem(BaseModel):
    reading_status: str | None = None


class BatchInteractionRequest(BaseModel):
    book_ids: list[uuid.UUID]


class BatchInteractionResponse(BaseModel):
    interactions: dict[str, BatchInteractionItem]
