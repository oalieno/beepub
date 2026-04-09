import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class WorkBookBrief(BaseModel):
    id: uuid.UUID
    display_title: str | None = None
    display_authors: list[str] | None = None
    cover_path: str | None = None
    epub_isbn: str | None = None
    metadata_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkOut(BaseModel):
    id: uuid.UUID
    title: str
    authors: list[str] | None = None
    primary_book_id: uuid.UUID | None = None
    books: list[WorkBookBrief] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkCreate(BaseModel):
    book_ids: list[uuid.UUID]

    @field_validator("book_ids")
    @classmethod
    def at_least_two(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(v) < 2:
            msg = "At least 2 books are required to create a Work"
            raise ValueError(msg)
        return v


class WorkUpdate(BaseModel):
    title: str | None = None
    authors: list[str] | None = None
    primary_book_id: uuid.UUID | None = None


class DuplicateGroup(BaseModel):
    books: list[WorkBookBrief]
    match_method: str  # "exact" or "fuzzy"


class DuplicateSuggestionsOut(BaseModel):
    groups: list[DuplicateGroup]
    total_books_scanned: int
    truncated: bool = False
