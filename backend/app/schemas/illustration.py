import uuid
from datetime import datetime

from pydantic import BaseModel


class IllustrationCreate(BaseModel):
    cfi_range: str
    text: str
    style_prompt: str | None = None
    custom_prompt: str | None = None


class IllustrationOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    cfi_range: str
    text: str
    style_prompt: str | None
    custom_prompt: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StylePromptOut(BaseModel):
    key: str
    label: str
    description: str
