import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.user import UserRole


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    role: UserRole
    is_active: bool
    can_download: bool
    can_upload: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateRole(BaseModel):
    role: UserRole


class UserUpdatePermissions(BaseModel):
    # None = leave unchanged, so callers can toggle one permission at a time.
    can_download: bool | None = None
    can_upload: bool | None = None


class AdminCreateUser(BaseModel):
    username: str
    password: str


class AdminResetPassword(BaseModel):
    new_password: str


class UserLibraryAccessOut(BaseModel):
    library_id: uuid.UUID
    library_name: str
    excluded: bool


class UserLibraryAccessUpdate(BaseModel):
    excluded_library_ids: list[uuid.UUID]
