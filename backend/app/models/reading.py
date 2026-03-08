import uuid
import enum
from datetime import datetime, date
from sqlalchemy import String, Text, SmallInteger, Boolean, ForeignKey, DateTime, Date, func
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class ReadingStatus(str, enum.Enum):
    want_to_read = "want_to_read"
    currently_reading = "currently_reading"
    read = "read"
    did_not_finish = "did_not_finish"


class UserBookInteraction(Base):
    __tablename__ = "user_book_interactions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reading_progress: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reading_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    finished_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="interactions")
    book: Mapped["Book"] = relationship("Book", back_populates="interactions")


class ReadingActivity(Base):
    __tablename__ = "reading_activity"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    seconds: Mapped[int] = mapped_column(nullable=False, default=0)


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    cfi_range: Mapped[str] = mapped_column(String(2000), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="yellow")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="highlights")
    book: Mapped["Book"] = relationship("Book", back_populates="highlights")
