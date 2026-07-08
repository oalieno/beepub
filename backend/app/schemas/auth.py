from typing import Any

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UpdateUsernameRequest(BaseModel):
    new_username: str = Field(min_length=1, max_length=50)

    @field_validator("new_username", mode="before")
    @classmethod
    def strip_username(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Username is required")
        return stripped


class LoginResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    is_demo: bool = False
    access_token: str
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
