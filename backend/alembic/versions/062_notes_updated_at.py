"""LWW stamp for book notes

Book notes become editable on-device (local books, offline), so they get
their own sync stamp like status/rating/favorite (052). Existing notes
are stamped from updated_at — the same backfill 052 used.

Revision ID: 062
Revises: 061
"""

import sqlalchemy as sa

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_book_interactions",
        sa.Column("notes_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE user_book_interactions SET notes_updated_at = updated_at"
        " WHERE notes IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("user_book_interactions", "notes_updated_at")
