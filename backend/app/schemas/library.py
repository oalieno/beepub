import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.library import LibraryVisibility


class LibraryCreate(BaseModel):
    name: str
    description: str | None = None
    visibility: LibraryVisibility = LibraryVisibility.public


class LibraryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    visibility: LibraryVisibility | None = None


class LibraryOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    cover_image: str | None
    visibility: LibraryVisibility
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class LibraryListOut(LibraryOut):
    book_count: int = 0
    preview_book_ids: list[uuid.UUID] = []


class LibraryMemberAdd(BaseModel):
    user_id: uuid.UUID


class LibraryMemberOut(BaseModel):
    user_id: uuid.UUID
    granted_by: uuid.UUID
    granted_at: datetime

    model_config = {"from_attributes": True}


class LibraryBookAdd(BaseModel):
    book_id: uuid.UUID
