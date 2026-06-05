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
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateRole(BaseModel):
    role: UserRole


class UserUpdatePermissions(BaseModel):
    can_download: bool


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
