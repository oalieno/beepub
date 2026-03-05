import uuid
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Illustration(Base):
    __tablename__ = "illustrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    cfi_range: Mapped[str] = mapped_column(String(2000), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    style_prompt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    user: Mapped["User"] = relationship("User")
    book: Mapped["Book"] = relationship("Book")
