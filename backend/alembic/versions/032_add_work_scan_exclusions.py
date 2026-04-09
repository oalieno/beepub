"""Add work_scan_exclusions table for permanent duplicate dismissals.

Revision ID: 032
Revises: 031
Create Date: 2026-04-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_scan_exclusions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id_a",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "book_id_b",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("book_id_a", "book_id_b"),
    )


def downgrade() -> None:
    op.drop_table("work_scan_exclusions")
