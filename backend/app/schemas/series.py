import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.book import BookOut, BookWithInteractionOut


class SeriesOut(BaseModel):
    series_key: str
    series_name: str
    library_id: uuid.UUID  # series identity is (library_id, series_key)
    library_name: str | None = None
    book_count: int
    read_count: int
    rating: float | None = None  # the user's explicit series rating
    notes: str | None = None
    cover_book: BookOut | None = None


class GroupedSeries(BaseModel):
    type: Literal["series"] = "series"
    series: SeriesOut


class GroupedBook(BaseModel):
    type: Literal["book"] = "book"
    book: BookWithInteractionOut


# One unit in the collapsed library view: a whole series or a lone book.
GroupedItem = Annotated[GroupedSeries | GroupedBook, Field(discriminator="type")]


class PaginatedGrouped(BaseModel):
    items: list[GroupedItem]
    total: int


class SeriesRatingUpdate(BaseModel):
    series_name: str
    library_id: uuid.UUID
    rating: float | None = None  # 0.5-5 in 0.5 steps, or null


class SeriesNotesUpdate(BaseModel):
    series_name: str
    library_id: uuid.UUID
    notes: str | None = None  # markdown
