"""Work model — groups multiple Book editions of the same logical work.

Architecture:
  ┌──────────┐     ┌──────────┐
  │  Work    │◄────│  Book    │  Book.work_id FK (nullable, SET NULL on delete)
  │          │     │          │
  │ id       │     │ work_id  │
  │ title    │     └──────────┘
  │ authors  │
  │ primary_ │
  │ book_id  │──► one Book (nullable, SET NULL on delete, post_update=True)
  └──────────┘
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.book import Book


class Work(Base, TimestampMixin):
    __tablename__ = "works"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    primary_book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    books: Mapped[list[Book]] = relationship(
        "Book",
        back_populates="work",
        foreign_keys="Book.work_id",
        passive_deletes=True,
    )
    primary_book: Mapped[Book | None] = relationship(
        "Book",
        foreign_keys=[primary_book_id],
        post_update=True,
    )


class WorkScanExclusion(Base, TimestampMixin):
    """Pairs of books that should never be grouped as duplicate editions."""

    __tablename__ = "work_scan_exclusions"
    __table_args__ = (UniqueConstraint("book_id_a", "book_id_b"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    book_id_a: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    book_id_b: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
