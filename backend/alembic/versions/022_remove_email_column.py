"""Remove email column from users table.

Self-hosted project does not need email.

Revision ID: 022
Revises: 021
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "email")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email", sa.String(255), unique=True, nullable=True),
    )
