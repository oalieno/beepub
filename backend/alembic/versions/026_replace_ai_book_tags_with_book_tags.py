"""Replace ai_book_tags with book_tags, extend MetadataSource enum.

Revision ID: 026
Revises: 025
Create Date: 2026-03-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old table and enum
    op.drop_table("ai_book_tags")
    op.execute("DROP TYPE IF EXISTS tagcategory")

    # Create new enums and table using raw SQL to avoid SQLAlchemy auto-creating types
    op.execute("DROP TYPE IF EXISTS tagcategory_v2")
    op.execute("DROP TYPE IF EXISTS tagsource")
    op.execute(
        "CREATE TYPE tagcategory_v2 AS ENUM ('genre', 'subgenre', 'mood', 'theme', 'trope')"
    )
    op.execute("CREATE TYPE tagsource AS ENUM ('external', 'epub', 'manual', 'ai')")

    op.execute("""
        CREATE TABLE book_tags (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            category tagcategory_v2 NOT NULL,
            source tagsource NOT NULL,
            confidence FLOAT NOT NULL DEFAULT 1.0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_book_tags_book_tag UNIQUE (book_id, tag)
        )
    """)
    op.execute("CREATE INDEX ix_book_tags_book_id ON book_tags (book_id)")
    op.execute("CREATE INDEX ix_book_tags_tag ON book_tags (tag)")
    op.execute("CREATE INDEX ix_book_tags_category ON book_tags (category)")
    op.execute("CREATE INDEX ix_book_tags_source ON book_tags (source)")

    # Migrate books.epub_tags → book_tags with source='epub'
    op.execute("""
        INSERT INTO book_tags (id, book_id, tag, category, source, confidence)
        SELECT
            gen_random_uuid(),
            b.id,
            unnest(b.epub_tags),
            'genre',
            'epub',
            1.0
        FROM books b
        WHERE b.epub_tags IS NOT NULL AND array_length(b.epub_tags, 1) > 0
        ON CONFLICT (book_id, tag) DO NOTHING
    """)

    # Migrate books.tags (manual overrides) → book_tags with source='manual'
    op.execute("""
        INSERT INTO book_tags (id, book_id, tag, category, source, confidence)
        SELECT
            gen_random_uuid(),
            b.id,
            unnest(b.tags),
            'genre',
            'manual',
            1.0
        FROM books b
        WHERE b.tags IS NOT NULL AND array_length(b.tags, 1) > 0
        ON CONFLICT (book_id, tag) DO UPDATE SET source = 'manual'
    """)

    # Extend metadatasource enum with new values
    op.execute("ALTER TYPE metadatasource ADD VALUE IF NOT EXISTS 'google_books'")
    op.execute("ALTER TYPE metadatasource ADD VALUE IF NOT EXISTS 'hardcover'")


def downgrade() -> None:
    op.drop_table("book_tags")
    op.execute("DROP TYPE IF EXISTS tagcategory_v2")
    op.execute("DROP TYPE IF EXISTS tagsource")

    # Recreate old enum and table
    op.execute("CREATE TYPE tagcategory AS ENUM ('genre', 'mood', 'topic')")
    op.create_table(
        "ai_book_tags",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(100), nullable=False),
        sa.Column(
            "category",
            sa.Enum("genre", "mood", "topic", name="tagcategory", create_type=False),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("book_id", "tag", name="uq_ai_book_tags_book_tag"),
    )
    op.create_index("ix_ai_book_tags_book_id", "ai_book_tags", ["book_id"])
    op.create_index("ix_ai_book_tags_tag", "ai_book_tags", ["tag"])
    op.create_index("ix_ai_book_tags_category", "ai_book_tags", ["category"])
