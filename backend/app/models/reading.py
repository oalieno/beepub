import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class ReadingStatus(enum.StrEnum):
    want_to_read = "want_to_read"
    currently_reading = "currently_reading"
    read = "read"
    did_not_finish = "did_not_finish"


class UserBookInteraction(Base):
    __tablename__ = "user_book_interactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    rating: Mapped[float | None] = mapped_column(
        Numeric(2, 1, asdecimal=False), nullable=True
    )
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
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="interactions")
    book: Mapped["Book"] = relationship("Book", back_populates="interactions")


class UserSeriesInteraction(Base):
    """Per-user rating/notes for a whole series.

    Series have no entity table — they are identified by the normalised series
    name (lower(btrim(coalesce(series, epub_series)))) scoped to a library, the
    same key used for popularity/recommendation grouping. This row hangs metadata
    off that (library_id, series_key) pair without touching the book-level series
    text fields.
    """

    __tablename__ = "user_series_interactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Series identity is scoped per library: the same normalised name in two
    # libraries (e.g. a light novel and its manga adaptation) is two series.
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), primary_key=True
    )
    series_key: Mapped[str] = mapped_column(String(500), primary_key=True)
    # Display name (original casing) captured when the row was created.
    series_name: Mapped[str] = mapped_column(String(500), nullable=False)
    rating: Mapped[float | None] = mapped_column(
        Numeric(2, 1, asdecimal=False), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# The web reader's live accumulator writes this device row; app devices
# mint their own ids and REPLACE their rows via /api/activity/sync.
WEB_DEVICE_ID = "web"


class ReadingActivity(Base):
    __tablename__ = "reading_activity"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=WEB_DEVICE_ID
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    seconds: Mapped[int] = mapped_column(nullable=False, default=0)


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    cfi_range: Mapped[str] = mapped_column(String(2000), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="yellow")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TextQuoteSelector context (W3C Annotation style): raw material for
    # re-anchoring when the cfi_range stops resolving (file rewritten).
    # Nullable — highlights created before this existed only have `text`.
    prefix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suffix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_index: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Soft-delete tombstone: a deletion must propagate to offline devices,
    # so DELETE stamps this instead of removing the row. Filtered out of
    # every list; cleared when a client re-creates the same id.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="highlights")
    book: Mapped["Book"] = relationship("Book", back_populates="highlights")
