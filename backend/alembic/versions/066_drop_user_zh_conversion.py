"""Drop the per-user Simplified-to-Traditional upload setting

Uploads are no longer converted unasked: an upload that brings books
reading as Simplified Chinese ends with a question, every time, so the
uploader knows a conversion was made. The setting that converted them at
ingest (061) goes. Its values are not kept: whoever had it on is asked
from now on.

Revision ID: 066
Revises: 065
"""

import sqlalchemy as sa

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "upload_zh_conversion")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("upload_zh_conversion", sa.String(length=8), nullable=True)
    )
