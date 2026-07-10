"""Shared cache of epub.js reading locations

Locations (the CFI anchors epub.js uses for canonical percentages) are
deterministic per book file but take seconds to generate client-side for
large books. The first client to finish uploads them; everyone else — any
user, device, or browser — downloads instead of regenerating. Rows are
invalidated when calibre rewrites the underlying file.

Revision ID: 047
Revises: 046
"""

import sqlalchemy as sa

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("book_locations")
