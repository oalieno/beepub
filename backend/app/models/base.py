import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
