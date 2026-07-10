"""Highlight anchor context (TextQuoteSelector raw material)

A highlight's cfi_range stops resolving when the book file is rewritten
(calibre metadata edit, re-conversion). Store the selection's surrounding
text (prefix/suffix, W3C TextQuoteSelector style) and the spine index at
creation time so a broken CFI can be re-anchored by quote search within
its section instead of silently disappearing.

Nullable: pre-existing highlights only have `text` and re-anchor degraded.

Revision ID: 049
Revises: 048
"""

import sqlalchemy as sa

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("highlights", sa.Column("prefix", sa.String(255), nullable=True))
    op.add_column("highlights", sa.Column("suffix", sa.String(255), nullable=True))
    op.add_column("highlights", sa.Column("section_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("highlights", "section_index")
    op.drop_column("highlights", "suffix")
    op.drop_column("highlights", "prefix")
