from typing import Literal

from pydantic import BaseModel

from app.schemas.book import BookOut, BookWithInteractionOut


class SeriesOut(BaseModel):
    series_key: str
    series_name: str
    book_count: int
    read_count: int
    rating: float | None = None  # explicit series rating
    effective_rating: float | None = None  # explicit, else best volume rating
    notes: str | None = None
    cover_book: BookOut | None = None


class PaginatedSeries(BaseModel):
    items: list[SeriesOut]
    total: int


class LibraryFeedItem(BaseModel):
    """One unit in the collapsed library view: a whole series or a lone book."""

    type: Literal["series", "book"]
    series: SeriesOut | None = None
    book: BookWithInteractionOut | None = None


class PaginatedFeed(BaseModel):
    items: list[LibraryFeedItem]
    total: int


class SeriesRatingUpdate(BaseModel):
    series_name: str
    rating: float | None = None  # 0.5-5 in 0.5 steps, or null


class SeriesNotesUpdate(BaseModel):
    series_name: str
    notes: str | None = None  # markdown
