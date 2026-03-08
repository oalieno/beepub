import uuid
from datetime import datetime

from pydantic import BaseModel


class BookshelfCreate(BaseModel):
    name: str
    description: str | None = None
    is_public: bool = False


class BookshelfUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_public: bool | None = None


class BookshelfOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BookshelfListOut(BookshelfOut):
    book_count: int = 0
    preview_book_ids: list[uuid.UUID] = []


class BookshelfBookAdd(BaseModel):
    book_id: uuid.UUID


class BookshelfReorder(BaseModel):
    book_ids: list[uuid.UUID]
