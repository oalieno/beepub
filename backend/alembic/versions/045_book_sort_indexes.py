"""Indexes for the default book list sort columns

Every paginated book list orders by created_at or by the "added_at"
alias COALESCE(calibre_added_at, created_at); neither had an index, so
each page request sorted the full filtered set. The id tiebreak on top
of these is handled by incremental sort.

Revision ID: 045
Revises: 044
"""

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_books_created_at ON books (created_at)")
    # Must match the SQLAlchemy-generated coalesce expression for "added_at"
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_books_added_at "
        "ON books ((COALESCE(calibre_added_at, created_at)))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_books_added_at")
    op.execute("DROP INDEX IF EXISTS ix_books_created_at")
