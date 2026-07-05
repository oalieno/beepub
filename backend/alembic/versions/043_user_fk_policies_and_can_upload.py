"""User actor FKs get ON DELETE SET NULL; add users.can_upload

Deleting a user previously hit ForeignKeyViolation (500) as soon as they
had uploaded a book, created a library, or excluded someone from one:
books.added_by, libraries.created_by, library_books.added_by, and
user_library_exclusions.excluded_by all defaulted to NO ACTION. Audit
columns shouldn't block deletion — null them out instead.

Revision ID: 043
Revises: 042
"""

import sqlalchemy as sa

from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None

ACTOR_FKS = [
    ("books", "added_by", "books_added_by_fkey"),
    ("libraries", "created_by", "libraries_created_by_fkey"),
    ("library_books", "added_by", "library_books_added_by_fkey"),
    (
        "user_library_exclusions",
        "excluded_by",
        "user_library_exclusions_excluded_by_fkey",
    ),
]


def upgrade() -> None:
    for table, column, conname in ACTOR_FKS:
        op.alter_column(table, column, nullable=True)
        op.drop_constraint(conname, table, type_="foreignkey")
        op.create_foreign_key(
            conname, table, "users", [column], ["id"], ondelete="SET NULL"
        )

    op.add_column(
        "users",
        sa.Column("can_upload", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "can_upload")

    for table, column, conname in ACTOR_FKS:
        op.drop_constraint(conname, table, type_="foreignkey")
        op.create_foreign_key(conname, table, "users", [column], ["id"])
        # NOTE: rows nulled by a user deletion can't be restored; leave the
        # column nullable on downgrade rather than failing on NOT NULL.
