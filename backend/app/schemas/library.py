import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.library import LibraryVisibility


class LibraryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    visibility: LibraryVisibility = LibraryVisibility.public


class LibraryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[LibraryVisibility] = None


class LibraryOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    cover_image: Optional[str]
    visibility: LibraryVisibility
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class LibraryMemberAdd(BaseModel):
    user_id: uuid.UUID


class LibraryMemberOut(BaseModel):
    user_id: uuid.UUID
    granted_by: uuid.UUID
    granted_at: datetime

    model_config = {"from_attributes": True}


class LibraryBookAdd(BaseModel):
    book_id: uuid.UUID
