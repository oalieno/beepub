"""add llm_usage_log table

Revision ID: 016
Revises: 015
Create Date: 2026-03-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("book_id", sa.Uuid(), nullable=True),
        sa.Column("feature", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_llm_usage_log_created_at", "llm_usage_log", ["created_at"])
    op.create_index("ix_llm_usage_log_feature", "llm_usage_log", ["feature"])
    op.create_index("ix_llm_usage_log_user_id", "llm_usage_log", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_log_user_id", table_name="llm_usage_log")
    op.drop_index("ix_llm_usage_log_feature", table_name="llm_usage_log")
    op.drop_index("ix_llm_usage_log_created_at", table_name="llm_usage_log")
    op.drop_table("llm_usage_log")
