import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.models.user import UserRole


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    role: UserRole
    is_active: bool
    can_download: bool
    can_upload: bool
    created_at: datetime
    # Demo-mode account restrictions (no username/password changes) are
    # enforced server-side; this lets the UI hide those controls too.
    is_demo: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _mark_demo(self) -> "UserOut":
        self.is_demo = bool(
            settings.demo_mode and self.username == settings.demo_username
        )
        return self


class UserUpdateRole(BaseModel):
    role: UserRole


class UserUpdatePermissions(BaseModel):
    # None = leave unchanged, so callers can toggle one permission at a time.
    can_download: bool | None = None
    can_upload: bool | None = None


class AdminCreateUser(BaseModel):
    username: str
    password: str = Field(min_length=8)


class AdminResetPassword(BaseModel):
    new_password: str = Field(min_length=8)


class UserLibraryAccessOut(BaseModel):
    library_id: uuid.UUID
    library_name: str
    excluded: bool


class UserLibraryAccessUpdate(BaseModel):
    excluded_library_ids: list[uuid.UUID]
