"""add ai_book_tags table

Revision ID: 011
Revises: 010
Create Date: 2024-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_book_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tag", sa.String(100), nullable=False, index=True),
        sa.Column(
            "category",
            sa.Enum("genre", "mood", "topic", name="tagcategory"),
            nullable=False,
            index=True,
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("book_id", "tag", name="uq_ai_book_tags_book_tag"),
    )


def downgrade() -> None:
    op.drop_table("ai_book_tags")
    sa.Enum("genre", "mood", "topic", name="tagcategory").drop(op.get_bind())
