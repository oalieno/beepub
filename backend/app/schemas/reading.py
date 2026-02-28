import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class RatingUpdate(BaseModel):
    rating: Optional[int] = None  # 1-5 or null


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class ProgressUpdate(BaseModel):
    cfi: str
    percentage: float


class ProgressOut(BaseModel):
    cfi: Optional[str] = None
    percentage: Optional[float] = None
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


class InteractionOut(BaseModel):
    rating: Optional[int]
    is_favorite: bool
    reading_progress: Optional[dict]
    updated_at: datetime

    model_config = {"from_attributes": True}
