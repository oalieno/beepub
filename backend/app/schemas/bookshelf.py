import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class BookshelfCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_public: bool = False


class BookshelfUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None


class BookshelfOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: Optional[str]
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
