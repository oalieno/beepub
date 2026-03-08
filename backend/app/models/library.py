import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class LibraryVisibility(str, enum.Enum):
    public = "public"
    private = "private"


class Library(Base, TimestampMixin):
    __tablename__ = "libraries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    visibility: Mapped[LibraryVisibility] = mapped_column(
        SAEnum(LibraryVisibility), nullable=False, default=LibraryVisibility.public
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    # Relationships
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    accesses: Mapped[list["LibraryAccess"]] = relationship(
        "LibraryAccess", back_populates="library"
    )
    library_books: Mapped[list["LibraryBook"]] = relationship(
        "LibraryBook", back_populates="library"
    )


class LibraryAccess(Base):
    __tablename__ = "library_access"

    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    library: Mapped["Library"] = relationship("Library", back_populates="accesses")
    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], back_populates="library_accesses"
    )
    granter: Mapped["User"] = relationship("User", foreign_keys=[granted_by])


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
