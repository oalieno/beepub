"""Trigram indexes for tag columns joining the book search

Topic queries (「二戰 納粹」) can't be served by title/author columns
alone — tags are where topics live, so book_search now matches them
too. Raw + normalized expression indexes keep those disjuncts off a
sequential scan (same shapes as 044/056; beepub_join_authors is a
generic array joiner despite the name).

Revision ID: 058
Revises: 057
"""

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_books_tags_trgm": "beepub_join_authors(tags)",
    "ix_books_epub_tags_trgm": "beepub_join_authors(epub_tags)",
    "ix_books_tags_norm_trgm": "beepub_norm(beepub_join_authors(tags))",
    "ix_books_epub_tags_norm_trgm": "beepub_norm(beepub_join_authors(epub_tags))",
}


def upgrade() -> None:
    for name, expr in INDEXES.items():
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} "
            f"ON books USING gin (({expr}) gin_trgm_ops)"
        )


def downgrade() -> None:
    for name in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
