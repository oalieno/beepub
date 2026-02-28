import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr
from app.models.user import UserRole


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None = None
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateRole(BaseModel):
    role: UserRole
