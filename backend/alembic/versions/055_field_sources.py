"""Per-field metadata provenance

books.field_sources records where each override column's current value
came from: {"description": "readmoo", "title": "manual", ...}. Written
by the edit-metadata page when a version is picked (source name) or a
field is hand-edited ("manual"); a key disappears when the override is
cleared back to the EPUB original. NULL = nothing recorded (pre-055
edits stay unattributed).

Revision ID: 055
Revises: 054
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("field_sources", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("books", "field_sources")
