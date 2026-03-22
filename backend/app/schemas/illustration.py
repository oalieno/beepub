import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class ReferenceImageInput(BaseModel):
    source: Literal["epub", "illustration"]
    path: str  # epub: zip path; illustration: UUID string


class IllustrationCreate(BaseModel):
    cfi_range: str
    text: str
    style_prompt: str | None = None
    custom_prompt: str | None = None
    reference_images: list[ReferenceImageInput] | None = None

    @field_validator("reference_images")
    @classmethod
    def max_four(
        cls, v: list[ReferenceImageInput] | None
    ) -> list[ReferenceImageInput] | None:
        if v and len(v) > 4:
            raise ValueError("Maximum 4 reference images")
        return v


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


class EpubImageOut(BaseModel):
    path: str
    name: str
