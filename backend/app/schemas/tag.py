import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.book import BookOut


class BookTagOut(BaseModel):
    id: uuid.UUID
    tag: str
    category: str
    source: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}


class TagWithCount(BaseModel):
    tag: str
    label: str
    category: str
    book_count: int


class SimilarBookOut(BookOut):
    similarity_score: float
    cosine_similarity: float | None = None


class TagBrowseSection(BaseModel):
    tag: str
    label: str
    category: str
    book_count: int
    books: list[BookOut]
