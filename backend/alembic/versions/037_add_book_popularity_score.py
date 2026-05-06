"""Add books.popularity_score (persisted external popularity) + index.

Revision ID: 037
Revises: 036
Create Date: 2026-05-06
"""

import sqlalchemy as sa

from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column(
            "popularity_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_books_popularity_score",
        "books",
        [sa.text("popularity_score DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_books_popularity_score", table_name="books")
    op.drop_column("books", "popularity_score")
