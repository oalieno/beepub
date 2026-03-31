import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.bookshelf import Bookshelf
    from app.models.library import LibraryAccess
    from app.models.reading import Highlight, UserBookInteraction


class UserRole(enum.StrEnum):
    admin = "admin"
    user = "user"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole), nullable=False, default=UserRole.user
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    daily_reading_goal_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Relationships
    library_accesses: Mapped[list["LibraryAccess"]] = relationship(
        "LibraryAccess",
        foreign_keys="LibraryAccess.user_id",
        back_populates="user",
        passive_deletes=True,
    )
    bookshelves: Mapped[list["Bookshelf"]] = relationship(
        "Bookshelf", back_populates="user", passive_deletes=True
    )
    interactions: Mapped[list["UserBookInteraction"]] = relationship(
        "UserBookInteraction", back_populates="user", passive_deletes=True
    )
    highlights: Mapped[list["Highlight"]] = relationship(
        "Highlight", back_populates="user", passive_deletes=True
    )
