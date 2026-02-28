import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Enum as SAEnum, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.database import Base
from app.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False, default=UserRole.user)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    library_accesses: Mapped[list["LibraryAccess"]] = relationship("LibraryAccess", foreign_keys="LibraryAccess.user_id", back_populates="user")
    bookshelves: Mapped[list["Bookshelf"]] = relationship("Bookshelf", back_populates="user")
    interactions: Mapped[list["UserBookInteraction"]] = relationship("UserBookInteraction", back_populates="user")
    highlights: Mapped[list["Highlight"]] = relationship("Highlight", back_populates="user")
