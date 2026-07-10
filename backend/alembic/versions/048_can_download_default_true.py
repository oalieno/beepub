"""Downloads allowed by default

can_download=False by default broke OPDS/kosync for every non-admin
account as an opaque "download failed" inside e-reader clients — a
failure the admin (who bypasses the gate) never sees. Users can already
read entire books online, so withholding the file is meaningful only as
a deliberate per-user restriction; flip the default and backfill.

Backfilling everyone erases no admin intent: False was the default, so
the only explicit choice an admin could have made was granting True.

Revision ID: 048
Revises: 047
"""

import sqlalchemy as sa

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "can_download", server_default=sa.text("true"))
    op.execute("UPDATE users SET can_download = true")


def downgrade() -> None:
    # Restores the old default only; granted permissions are not revoked.
    op.alter_column("users", "can_download", server_default=sa.text("false"))
