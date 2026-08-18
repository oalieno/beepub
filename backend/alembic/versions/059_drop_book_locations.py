"""Drop the shared epub.js locations cache

The reader no longer generates or reads epub.js locations — progress
percentages are interpolated from per-section text weights derived on
read from book_text_chunks (see BookOut.section_weights). The shared
cache this table backed was also the root of the poisoned-progress bug:
partial generations on flaky networks were stored as complete and then
served to every user. Nothing reads or writes the table anymore.

Revision ID: 059
Revises: 058
"""

import sqlalchemy as sa

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("book_locations")


def downgrade() -> None:
    # Recreated empty (mirrors 047) — the cache repopulates lazily from
    # clients on the old code.
    op.create_table(
        "book_locations",
        sa.Column(
            "book_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fingerprint", sa.String(255), nullable=False),
        sa.Column("locations", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
