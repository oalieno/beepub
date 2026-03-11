from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.bookshelf import BookshelfBook
    from app.models.library import LibraryBook
    from app.models.reading import Highlight, UserBookInteraction
    from app.models.user import User


class MetadataSource(enum.StrEnum):
    goodreads = "goodreads"
    readmoo = "readmoo"


class Book(Base, TimestampMixin):
    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="epub")
    cover_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # EPUB original metadata
    epub_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    epub_authors: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    epub_publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    epub_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    epub_isbn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    epub_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    epub_published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Manual overrides (take priority in display)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)

    calibre_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    calibre_added_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Relationships
    uploader: Mapped[User] = relationship("User", foreign_keys=[added_by])
    library_books: Mapped[list[LibraryBook]] = relationship(
        "LibraryBook", back_populates="book", cascade="all, delete-orphan"
    )
    external_metadata: Mapped[list[ExternalMetadata]] = relationship(
        "ExternalMetadata", back_populates="book", cascade="all, delete-orphan"
    )
    interactions: Mapped[list[UserBookInteraction]] = relationship(
        "UserBookInteraction", back_populates="book", cascade="all, delete-orphan"
    )
    highlights: Mapped[list[Highlight]] = relationship(
        "Highlight", back_populates="book", cascade="all, delete-orphan"
    )
    bookshelf_books: Mapped[list[BookshelfBook]] = relationship(
        "BookshelfBook", back_populates="book", cascade="all, delete-orphan"
    )

    @property
    def display_title(self) -> str | None:
        return self.title or self.epub_title

    @property
    def display_authors(self) -> list[str] | None:
        return self.authors or self.epub_authors


class ExternalMetadata(Base):
    __tablename__ = "external_metadata"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[MetadataSource] = mapped_column(
        SAEnum(MetadataSource), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviews: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    book: Mapped[Book] = relationship("Book", back_populates="external_metadata")

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "book_id", "source", name="uq_external_metadata_book_source"
        ),
    )
