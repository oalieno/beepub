import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KosyncProgress(Base):
    """Raw progress records pushed by KOReader's sync client.

    Keyed by the document digest the client computed (partial MD5 of the
    file by default), NOT by book id — records are stored even when the
    digest matches no book, so progress isn't lost for sideloaded copies.
    ``progress`` is opaque client state (an xpointer for EPUBs); it is
    stored and served verbatim so KOReader-to-KOReader sync keeps exact
    positions. ``percentage`` is 0–1 as sent by the client.
    """

    __tablename__ = "kosync_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    document: Mapped[str] = mapped_column(String(64), primary_key=True)
    progress: Mapped[str | None] = mapped_column(Text, nullable=True)
    percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    device: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
