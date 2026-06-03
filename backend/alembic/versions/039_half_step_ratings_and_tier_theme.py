"""Support half-step ratings (Numeric(2,1)) and per-user tier theme.

Revision ID: 039
Revises: 038
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_book_interactions",
        "rating",
        type_=sa.Numeric(2, 1),
        existing_type=sa.SmallInteger(),
        existing_nullable=True,
        postgresql_using="rating::numeric(2,1)",
    )
    op.add_column(
        "users",
        sa.Column("tier_theme", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tier_theme")
    op.alter_column(
        "user_book_interactions",
        "rating",
        type_=sa.SmallInteger(),
        existing_type=sa.Numeric(2, 1),
        existing_nullable=True,
        postgresql_using="round(rating)::smallint",
    )
