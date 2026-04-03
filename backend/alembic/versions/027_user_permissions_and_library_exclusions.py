"""Add user download permission, library exclusions (deny-list), drop old access model.

Revision ID: 027
Revises: 026
Create Date: 2026-04-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add can_download to users (default False)
    op.add_column(
        "users",
        sa.Column("can_download", sa.Boolean(), nullable=False, server_default="false"),
    )

    # 2. Set can_download=True for admin users
    op.execute("UPDATE users SET can_download = true WHERE role = 'admin'")

    # 3. Create user_library_exclusions table (deny-list)
    op.create_table(
        "user_library_exclusions",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "library_id",
            UUID(as_uuid=True),
            sa.ForeignKey("libraries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "excluded_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "excluded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 4. Add index on user_id for subquery performance
    op.create_index(
        "ix_user_library_exclusions_user_id",
        "user_library_exclusions",
        ["user_id"],
    )

    # 5. Drop old access model
    op.drop_table("library_access")
    op.drop_column("libraries", "visibility")
    op.execute("DROP TYPE IF EXISTS libraryvisibility")


def downgrade() -> None:
    # Recreate libraryvisibility enum
    op.execute("CREATE TYPE libraryvisibility AS ENUM ('public', 'private')")

    # Recreate visibility column
    op.add_column(
        "libraries",
        sa.Column(
            "visibility",
            sa.Enum("public", "private", name="libraryvisibility"),
            nullable=False,
            server_default="public",
        ),
    )

    # Recreate library_access table
    op.create_table(
        "library_access",
        sa.Column(
            "library_id",
            UUID(as_uuid=True),
            sa.ForeignKey("libraries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "granted_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Drop new tables/columns
    op.drop_index("ix_user_library_exclusions_user_id")
    op.drop_table("user_library_exclusions")
    op.drop_column("users", "can_download")
