"""add reading_status, started_at, finished_at, notes to user_book_interactions

Revision ID: 004
Revises: 003
Create Date: 2026-03-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_book_interactions",
        sa.Column("reading_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "user_book_interactions", sa.Column("started_at", sa.Date, nullable=True)
    )
    op.add_column(
        "user_book_interactions", sa.Column("finished_at", sa.Date, nullable=True)
    )
    op.add_column("user_book_interactions", sa.Column("notes", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("user_book_interactions", "notes")
    op.drop_column("user_book_interactions", "finished_at")
    op.drop_column("user_book_interactions", "started_at")
    op.drop_column("user_book_interactions", "reading_status")
