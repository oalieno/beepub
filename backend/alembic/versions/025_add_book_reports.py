"""Add book_reports table for issue tracking.

Revision ID: 025
Revises: 024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "book_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reported_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("issue_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "resolved_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_book_reports_book_id", "book_reports", ["book_id"])
    # Partial index for fast EXISTS subquery on unresolved reports
    op.create_index(
        "ix_book_reports_unresolved",
        "book_reports",
        ["book_id"],
        postgresql_where=sa.text("resolved = false"),
    )


def downgrade() -> None:
    op.drop_table("book_reports")
