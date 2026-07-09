"""KOReader progress sync (kosync): auth key, document digests, progress store

KOReader's sync client authenticates with md5(password) computed on the
device, which cannot be verified against our bcrypt(sha256(password))
hashes — so users.kosync_key_hash stores bcrypt(md5(password)), derived
whenever the server sees the plaintext (register, login, password change).
books.partial_md5 is KOReader's document digest, used to map synced
progress back to a book. kosync_progress stores the raw client records.

Revision ID: 046
Revises: 045
"""

import sqlalchemy as sa

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("kosync_key_hash", sa.String(255), nullable=True))
    op.add_column("books", sa.Column("partial_md5", sa.String(32), nullable=True))
    op.create_index("ix_books_partial_md5", "books", ["partial_md5"])
    op.create_table(
        "kosync_progress",
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("document", sa.String(64), primary_key=True),
        sa.Column("progress", sa.Text(), nullable=True),
        sa.Column("percentage", sa.Float(), nullable=True),
        sa.Column("device", sa.String(255), nullable=True),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("kosync_progress")
    op.drop_index("ix_books_partial_md5", table_name="books")
    op.drop_column("books", "partial_md5")
    op.drop_column("users", "kosync_key_hash")
