import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin


class LLMUsageLog(Base, TimestampMixin):
    __tablename__ = "llm_usage_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_llm_usage_log_created_at", "created_at"),
        Index("ix_llm_usage_log_feature", "feature"),
        Index("ix_llm_usage_log_user_id", "user_id"),
    )
