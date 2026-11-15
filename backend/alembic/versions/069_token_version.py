"""A user's logins can be ended: users.token_version

A login is a signed token that stays valid until it expires — up to
thirty days for the refresh token. Changing a password, or an admin
resetting one, did not end the logins made with the old one.

Each token now carries the version it was issued under, and is accepted
only while that is still the user's. Changing the password moves the
user to the next version. Tokens issued before this have no version and
count as 0, which is where every user starts — so upgrading logs nobody
out.

Revision ID: 069
Revises: 068
"""

import sqlalchemy as sa

from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
