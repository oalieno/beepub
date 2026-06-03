"""Per-user series interactions (rating/notes keyed by normalised series name).

Revision ID: 040
Revises: 039
Create Date: 2026-06-03
"""

import sqlalchemy as sa

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_series_interactions",
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("series_key", sa.String(500), primary_key=True),
        sa.Column("series_name", sa.String(500), nullable=False),
        sa.Column("rating", sa.Numeric(2, 1), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_series_interactions")
