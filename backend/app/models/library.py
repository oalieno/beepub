import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class Library(Base, TimestampMixin):
    __tablename__ = "libraries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    calibre_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, unique=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    # Relationships
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    exclusions: Mapped[list["UserLibraryExclusion"]] = relationship(
        "UserLibraryExclusion", back_populates="library", passive_deletes=True
    )
    library_books: Mapped[list["LibraryBook"]] = relationship(
        "LibraryBook", back_populates="library", passive_deletes=True
    )


class UserLibraryExclusion(Base):
    __tablename__ = "user_library_exclusions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), primary_key=True
    )
    excluded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    excluded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    library: Mapped["Library"] = relationship("Library", back_populates="exclusions")
    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], back_populates="library_exclusions"
    )
    excluder: Mapped["User"] = relationship("User", foreign_keys=[excluded_by])


class LibraryBook(Base):
    __tablename__ = "library_books"

    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), primary_key=True
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    library: Mapped["Library"] = relationship("Library", back_populates="library_books")
    book: Mapped["Book"] = relationship("Book", back_populates="library_books")
    adder: Mapped["User"] = relationship("User", foreign_keys=[added_by])
