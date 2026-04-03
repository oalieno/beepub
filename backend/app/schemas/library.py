import uuid
from datetime import datetime

from pydantic import BaseModel


class LibraryCreate(BaseModel):
    name: str
    description: str | None = None


class LibraryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class LibraryOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    cover_image: str | None
    calibre_path: str | None = None
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class LibraryListOut(LibraryOut):
    book_count: int = 0
    preview_book_ids: list[uuid.UUID] = []


class LibraryBookAdd(BaseModel):
    book_id: uuid.UUID
