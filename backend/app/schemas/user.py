import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.user import UserRole


class TierBand(BaseModel):
    min: float  # inclusive lower bound of this band (0.5-5)
    label: str  # e.g. "UR", "SSR", "S", "夯到拉"
    color: str  # CSS color / token


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    role: UserRole
    is_active: bool
    can_download: bool
    created_at: datetime
    tier_theme: list[TierBand] | None = None  # null = use default preset

    model_config = {"from_attributes": True}


class TierThemeUpdate(BaseModel):
    tier_theme: list[TierBand] | None = None  # null to reset to default preset


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
