import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class IllustrationCreate(BaseModel):
    cfi_range: str
    text: str
    style_prompt: Optional[str] = None
    custom_prompt: Optional[str] = None


class IllustrationOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    cfi_range: str
    text: str
    style_prompt: Optional[str]
    custom_prompt: Optional[str]
    status: str
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StylePromptOut(BaseModel):
    key: str
    label: str
    description: str
