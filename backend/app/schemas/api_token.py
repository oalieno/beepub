import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiTokenOut(BaseModel):
    id: uuid.UUID
    name: str
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ApiTokenCreated(ApiTokenOut):
    """Creation response — the only time the plaintext token is returned."""

    token: str


class ApiTokenVerifyOut(BaseModel):
    username: str
