"""Per-field LWW anchors on user_book_interactions

Device sync needs to merge manually-edited interaction fields (reading
status, rating, favorite), but the row-level updated_at bumps on every
progress write, so it can't order those edits. Each field group gets its
own timestamp: web mutations stamp server-now, sync clients supply their
own stamps and merge last-write-wins.

Backfill uses updated_at for rows where the field is set: without it a
device pushing a freshly-stamped value would always beat a pre-migration
web edit (NULL loses to everything). updated_at over-protects — progress
writes inflated it — but only for data that predates this migration.

Revision ID: 052
Revises: 051
"""

import sqlalchemy as sa

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_book_interactions",
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_book_interactions",
        sa.Column("rating_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_book_interactions",
        sa.Column("favorite_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE user_book_interactions
        SET status_updated_at = updated_at
        WHERE reading_status IS NOT NULL
           OR started_at IS NOT NULL
           OR finished_at IS NOT NULL
        """
    )
    op.execute(
        "UPDATE user_book_interactions SET rating_updated_at = updated_at"
        " WHERE rating IS NOT NULL"
    )
    op.execute(
        "UPDATE user_book_interactions SET favorite_updated_at = updated_at"
        " WHERE is_favorite"
    )


def downgrade() -> None:
    op.drop_column("user_book_interactions", "favorite_updated_at")
    op.drop_column("user_book_interactions", "rating_updated_at")
    op.drop_column("user_book_interactions", "status_updated_at")
