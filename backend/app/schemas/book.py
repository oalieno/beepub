import uuid
from datetime import datetime

from pydantic import BaseModel


class AiBookTagNested(BaseModel):
    id: uuid.UUID
    tag: str
    label: str = ""
    category: str
    confidence: float

    model_config = {"from_attributes": True}

    def model_post_init(self, __context: object) -> None:
        if not self.label:
            from app.services.tags import TAG_LABELS

            self.label = TAG_LABELS.get(self.tag, self.tag)


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
    epub_series: str | None = None
    epub_series_index: float | None = None
    epub_tags: list[str] | None = None
    title: str | None
    authors: list[str] | None
    publisher: str | None
    description: str | None
    published_date: str | None
    series: str | None = None
    series_index: float | None = None
    tags: list[str] | None = None
    word_count: int | None = None
    is_image_book: bool | None = None
    has_unresolved_reports: bool = False
    display_title: str | None
    display_authors: list[str] | None
    display_series: str | None = None
    display_series_index: float | None = None
    display_tags: list[str] | None = None
    ai_tags: list[AiBookTagNested] = []
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
    seed_book_id: uuid.UUID | None = None


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
    series: str | None = None
    series_index: float | None = None
    tags: list[str] | None = None


class SeriesBookBrief(BaseModel):
    id: uuid.UUID
    title: str | None
    authors: list[str] | None
    cover_path: str | None
    series_index: float | None

    model_config = {"from_attributes": True}


class SeriesProgress(BaseModel):
    total_in_library: int
    read_count: int


class SeriesNeighborsOut(BaseModel):
    series_name: str | None = None
    current_index: float | None = None
    next: SeriesBookBrief | None = None
    previous: SeriesBookBrief | None = None
    progress: SeriesProgress | None = None


class BookReportCreate(BaseModel):
    issue_type: str
    description: str | None = None


class BookReportOut(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    reported_by: uuid.UUID | None
    issue_type: str
    description: str | None
    resolved: bool
    resolved_by: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None
    book_title: str | None = None
    book_cover: str | None = None
    reporter_name: str | None = None

    model_config = {"from_attributes": True}


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
