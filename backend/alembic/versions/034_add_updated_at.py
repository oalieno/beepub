"""Add updated_at to all TimestampMixin tables.

Revision ID: 034
Revises: 033
Create Date: 2026-05-02
"""

import sqlalchemy as sa

from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


TABLES = [
    "books",
    "users",
    "libraries",
    "bookshelves",
    "works",
    "work_scan_exclusions",
    "llm_usage_log",
    "book_text_chunks",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        # Backfill: align updated_at with created_at for existing rows.
        op.execute(f"UPDATE {table} SET updated_at = created_at")


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "updated_at")
