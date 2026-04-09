"""Add works table for book edition grouping.

Revision ID: 031
Revises: 030
Create Date: 2026-04-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "works",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("authors", sa.ARRAY(sa.String), nullable=True),
        sa.Column(
            "primary_book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.add_column(
        "books",
        sa.Column(
            "work_id",
            UUID(as_uuid=True),
            sa.ForeignKey("works.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_books_work_id", "books", ["work_id"])


def downgrade() -> None:
    op.drop_index("idx_books_work_id", table_name="books")
    op.drop_column("books", "work_id")
    op.drop_table("works")
