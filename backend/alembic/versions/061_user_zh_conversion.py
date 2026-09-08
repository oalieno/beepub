"""Per-user Simplified-to-Traditional conversion at upload

`upload_zh_conversion` names the OpenCC configuration applied to uploads
detected as Simplified Chinese (TXT first): NULL leaves the text alone,
"s2tw" converts characters to the Taiwan standard, "s2twp" also swaps
Mainland phrases for Taiwan usage.

Revision ID: 061
Revises: 060
"""

import sqlalchemy as sa

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("upload_zh_conversion", sa.String(length=8), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "upload_zh_conversion")
