"""Add daily_reading_goal_seconds to users table.

Revision ID: 017
"""

import sqlalchemy as sa

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("daily_reading_goal_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "daily_reading_goal_seconds")
