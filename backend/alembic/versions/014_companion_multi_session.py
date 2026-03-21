"""companion multi-session: drop unique constraint, add title

Revision ID: 014
Revises: 013
Create Date: 2026-03-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companion_conversations",
        sa.Column("title", sa.String(length=200), nullable=True),
    )
    op.drop_constraint(
        "uq_companion_conv_book_user", "companion_conversations", type_="unique"
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_companion_conv_book_user",
        "companion_conversations",
        ["book_id", "user_id"],
    )
    op.drop_column("companion_conversations", "title")
