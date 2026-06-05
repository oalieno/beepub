import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class Bookshelf(Base, TimestampMixin):
    __tablename__ = "bookshelves"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bookshelves")
    bookshelf_books: Mapped[list["BookshelfBook"]] = relationship(
        "BookshelfBook", back_populates="bookshelf", cascade="all, delete-orphan"
    )


class BookshelfBook(Base):
    """A shelf membership row points at *either* a book or a whole series
    (by normalised series key) — exactly one is set."""

    __tablename__ = "bookshelf_books"
    __table_args__ = (
        CheckConstraint(
            "(book_id IS NOT NULL) <> (series_key IS NOT NULL)",
            name="ck_bookshelf_books_one_target",
        ),
        Index(
            "uq_bookshelf_books_book",
            "bookshelf_id",
            "book_id",
            unique=True,
            postgresql_where=text("book_id IS NOT NULL"),
        ),
        Index(
            "uq_bookshelf_books_series",
            "bookshelf_id",
            "series_key",
            unique=True,
            postgresql_where=text("series_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bookshelf_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookshelves.id", ondelete="CASCADE"), nullable=False
    )
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), nullable=True
    )
    series_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    bookshelf: Mapped["Bookshelf"] = relationship(
        "Bookshelf", back_populates="bookshelf_books"
    )
    book: Mapped["Book"] = relationship("Book", back_populates="bookshelf_books")
