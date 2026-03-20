from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book import Book


class TagCategory(enum.StrEnum):
    genre = "genre"
    mood = "mood"
    topic = "topic"


class AiBookTag(Base):
    __tablename__ = "ai_book_tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[TagCategory] = mapped_column(
        SAEnum(TagCategory), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    book: Mapped[Book] = relationship("Book", back_populates="ai_tags")

    __table_args__ = (
        UniqueConstraint("book_id", "tag", name="uq_ai_book_tags_book_tag"),
    )
