import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class BookOut(BaseModel):
    id: uuid.UUID
    file_size: int
    format: str
    cover_path: Optional[str]
    epub_title: Optional[str]
    epub_authors: Optional[list[str]]
    epub_publisher: Optional[str]
    epub_language: Optional[str]
    epub_isbn: Optional[str]
    epub_description: Optional[str]
    epub_published_date: Optional[str]
    title: Optional[str]
    authors: Optional[list[str]]
    publisher: Optional[str]
    description: Optional[str]
    published_date: Optional[str]
    display_title: Optional[str]
    display_authors: Optional[list[str]]
    added_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class BookMetadataUpdate(BaseModel):
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    publisher: Optional[str] = None
    description: Optional[str] = None
    published_date: Optional[str] = None


class ExternalMetadataOut(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    source: str
    source_url: Optional[str]
    rating: Optional[float]
    rating_count: Optional[int]
    reviews: Optional[list]
    fetched_at: datetime

    model_config = {"from_attributes": True}
