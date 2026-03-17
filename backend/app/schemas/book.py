import uuid
from datetime import datetime

from pydantic import BaseModel


class BookOut(BaseModel):
    id: uuid.UUID
    file_size: int
    format: str
    cover_path: str | None
    epub_title: str | None
    epub_authors: list[str] | None
    epub_publisher: str | None
    epub_language: str | None
    epub_isbn: str | None
    epub_description: str | None
    epub_published_date: str | None
    title: str | None
    authors: list[str] | None
    publisher: str | None
    description: str | None
    published_date: str | None
    word_count: int | None = None
    display_title: str | None
    display_authors: list[str] | None
    calibre_id: int | None = None
    calibre_added_at: datetime | None = None
    added_by: uuid.UUID
    created_at: datetime
    library_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class PaginatedBooks(BaseModel):
    items: list[BookOut]
    total: int

    model_config = {"from_attributes": True}


class BookWithInteractionOut(BookOut):
    reading_status: str | None = None
    is_favorite: bool = False
    reading_percentage: float | None = None
    last_read_at: str | None = None


class PaginatedBooksWithInteraction(BaseModel):
    items: list[BookWithInteractionOut]
    total: int

    model_config = {"from_attributes": True}


class BookSearchResult(BookOut):
    library_name: str | None = None


class PaginatedBookSearchResults(BaseModel):
    items: list[BookSearchResult]
    total: int


class BookMetadataUpdate(BaseModel):
    title: str | None = None
    authors: list[str] | None = None
    publisher: str | None = None
    description: str | None = None
    published_date: str | None = None


class ExternalMetadataUrlUpdate(BaseModel):
    source_url: str | None = None


class ExternalMetadataOut(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    source: str
    source_url: str | None
    rating: float | None
    rating_count: int | None
    reviews: list | None
    fetched_at: datetime

    model_config = {"from_attributes": True}
