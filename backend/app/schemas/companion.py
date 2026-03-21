import uuid
from datetime import datetime

from pydantic import BaseModel


class CompanionMessageRequest(BaseModel):
    message: str
    selected_text: str | None = None
    cfi_range: str | None = None
    current_cfi: str | None = None
    conversation_id: uuid.UUID | None = None


class CompanionMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    selected_text: str | None
    cfi_range: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanionConversationOut(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    messages: list[CompanionMessageOut]
    created_at: datetime

    model_config = {"from_attributes": True}
