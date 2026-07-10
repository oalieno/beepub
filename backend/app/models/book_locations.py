"""Shared cache of epub.js reading locations.

Deterministic per book file (the fingerprint encodes identifier + spine
count + break size), so one client's generation serves every user and
device. Invalidated when calibre rewrites the file.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BookLocations(Base):
    __tablename__ = "book_locations"

    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    locations: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
