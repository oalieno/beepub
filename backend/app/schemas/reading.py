import uuid
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class RatingUpdate(BaseModel):
    rating: Optional[int] = None  # 1-5 or null


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class ProgressUpdate(BaseModel):
    cfi: str
    percentage: float
    current_page: Optional[int] = None
    font_size: Optional[int] = None
    section_index: Optional[int] = None
    section_page: Optional[int] = None
    section_page_counts: Optional[list[int]] = None
    total_pages: Optional[int] = None


class ProgressOut(BaseModel):
    cfi: Optional[str] = None
    percentage: Optional[float] = None
    current_page: Optional[int] = None
    font_size: Optional[int] = None
    section_index: Optional[int] = None
    section_page: Optional[int] = None
    section_page_counts: Optional[list[int]] = None
    total_pages: Optional[int] = None
    last_read_at: Optional[str] = None


class HighlightCreate(BaseModel):
    cfi_range: str
    text: str
    color: str = "yellow"
    note: Optional[str] = None


class HighlightUpdate(BaseModel):
    color: Optional[str] = None
    note: Optional[str] = None


class HighlightOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    cfi_range: str
    text: str
    color: str
    note: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReadingStatusUpdate(BaseModel):
    reading_status: Optional[str] = None  # want_to_read, currently_reading, read, did_not_finish
    started_at: Optional[date] = None
    finished_at: Optional[date] = None


class NotesUpdate(BaseModel):
    notes: Optional[str] = None  # markdown


class ReadingActivityOut(BaseModel):
    date: date
    seconds: int

    model_config = {"from_attributes": True}


class InteractionOut(BaseModel):
    rating: Optional[int]
    is_favorite: bool
    reading_progress: Optional[dict]
    reading_status: Optional[str]
    started_at: Optional[date]
    finished_at: Optional[date]
    notes: Optional[str]
    updated_at: datetime

    model_config = {"from_attributes": True}
