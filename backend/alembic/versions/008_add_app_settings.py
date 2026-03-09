"""add app_settings table

Revision ID: 008
Revises: 007
Create Date: 2024-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )

    # Insert default values
    op.execute(
        """
        INSERT INTO app_settings (key, value) VALUES
            ('timezone', 'Asia/Taipei'),
            ('metadata_refresh_enabled', 'true'),
            ('metadata_refresh_hour', '3'),
            ('metadata_refresh_interval_days', '7'),
            ('metadata_refresh_cooldown_days', '30')
        """
    )


def downgrade() -> None:
    op.drop_table("app_settings")
