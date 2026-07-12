"""Device-scoped reading activity

The old (user_id, date) accumulator can't take device uploads: sync
replays state, and replaying onto `seconds +=` double-counts. Each device
now owns its (user_id, device_id, date) rows and re-uploads REPLACE them;
the web reader's live accumulator keeps writing device_id='web'. Readers
aggregate across devices per date.

Revision ID: 051
Revises: 050
"""

import sqlalchemy as sa

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reading_activity",
        sa.Column("device_id", sa.String(64), nullable=False, server_default="web"),
    )
    op.drop_constraint("reading_activity_pkey", "reading_activity", type_="primary")
    op.create_primary_key(
        "reading_activity_pkey",
        "reading_activity",
        ["user_id", "device_id", "date"],
    )


def downgrade() -> None:
    op.drop_constraint("reading_activity_pkey", "reading_activity", type_="primary")
    # Collapse per-device rows into one summed row per (user, date).
    op.execute(
        """
        UPDATE reading_activity a
        SET seconds = t.total
        FROM (
            SELECT user_id, date, SUM(seconds) AS total,
                   MIN(device_id) AS keep_device
            FROM reading_activity GROUP BY user_id, date
        ) t
        WHERE a.user_id = t.user_id AND a.date = t.date
          AND a.device_id = t.keep_device
        """
    )
    op.execute(
        """
        DELETE FROM reading_activity a
        USING (
            SELECT user_id, date, MIN(device_id) AS keep_device
            FROM reading_activity GROUP BY user_id, date
        ) t
        WHERE a.user_id = t.user_id AND a.date = t.date
          AND a.device_id <> t.keep_device
        """
    )
    op.drop_column("reading_activity", "device_id")
    op.create_primary_key(
        "reading_activity_pkey", "reading_activity", ["user_id", "date"]
    )
