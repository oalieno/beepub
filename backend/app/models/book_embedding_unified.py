"""Book-level embeddings — one vector per book.

Source is either 'summary' (from concatenated chapter summaries, higher quality)
or 'chunk_avg' (average of chunk embedding vectors, fallback).
Summary always takes priority over chunk_avg.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BookEmbedding(Base):
    __tablename__ = "book_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    embedding = mapped_column(Vector(1024), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    source_summary_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="summary"
    )
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
