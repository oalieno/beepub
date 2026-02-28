"""initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum types (userrole, libraryvisibility, metadatasource) are pre-created
    # by start.sh via psql before alembic runs, so we just reference them here.

    # users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', postgresql.ENUM('admin', 'user', name='userrole', create_type=False), nullable=False, server_default='user'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # libraries
    op.create_table(
        'libraries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('cover_image', sa.String(500), nullable=True),
        sa.Column('visibility', postgresql.ENUM('public', 'private', name='libraryvisibility', create_type=False), nullable=False, server_default='public'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # library_access
    op.create_table(
        'library_access',
        sa.Column('library_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('libraries.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('granted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # books
    op.create_table(
        'books',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('file_size', sa.BigInteger, nullable=False),
        sa.Column('format', sa.String(10), nullable=False, server_default='epub'),
        sa.Column('cover_path', sa.String(500), nullable=True),
        sa.Column('epub_title', sa.String(500), nullable=True),
        sa.Column('epub_authors', postgresql.ARRAY(sa.String), nullable=True),
        sa.Column('epub_publisher', sa.String(255), nullable=True),
        sa.Column('epub_language', sa.String(10), nullable=True),
        sa.Column('epub_isbn', sa.String(20), nullable=True),
        sa.Column('epub_description', sa.Text, nullable=True),
        sa.Column('epub_published_date', sa.String(50), nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('authors', postgresql.ARRAY(sa.String), nullable=True),
        sa.Column('publisher', sa.String(255), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('published_date', sa.String(50), nullable=True),
        sa.Column('added_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # library_books
    op.create_table(
        'library_books',
        sa.Column('library_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('libraries.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('book_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('added_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # external_metadata
    op.create_table(
        'external_metadata',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('book_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', postgresql.ENUM('goodreads', 'readmoo', 'kobo_tw', name='metadatasource', create_type=False), nullable=False),
        sa.Column('source_url', sa.String(1000), nullable=True),
        sa.Column('rating', sa.Numeric(3, 2), nullable=True),
        sa.Column('rating_count', sa.Integer, nullable=True),
        sa.Column('reviews', postgresql.JSONB, nullable=True),
        sa.Column('raw_data', postgresql.JSONB, nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('book_id', 'source', name='uq_external_metadata_book_source'),
    )

    # bookshelves
    op.create_table(
        'bookshelves',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('is_public', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # bookshelf_books
    op.create_table(
        'bookshelf_books',
        sa.Column('bookshelf_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bookshelves.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('book_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # user_book_interactions
    op.create_table(
        'user_book_interactions',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('book_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('rating', sa.SmallInteger, nullable=True),
        sa.Column('is_favorite', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('reading_progress', postgresql.JSONB, nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # highlights
    op.create_table(
        'highlights',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('book_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cfi_range', sa.String(2000), nullable=False),
        sa.Column('text', sa.Text, nullable=False),
        sa.Column('color', sa.String(20), nullable=False, server_default='yellow'),
        sa.Column('note', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Indexes
    op.create_index('ix_books_epub_title', 'books', ['epub_title'])
    op.create_index('ix_books_title', 'books', ['title'])
    op.create_index('ix_highlights_user_book', 'highlights', ['user_id', 'book_id'])


def downgrade() -> None:
    op.drop_table('highlights')
    op.drop_table('user_book_interactions')
    op.drop_table('bookshelf_books')
    op.drop_table('bookshelves')
    op.drop_table('external_metadata')
    op.drop_table('library_books')
    op.drop_table('books')
    op.drop_table('library_access')
    op.drop_table('libraries')
    op.drop_table('users')
    op.execute("DROP TYPE IF EXISTS metadatasource")
    op.execute("DROP TYPE IF EXISTS libraryvisibility")
    op.execute("DROP TYPE IF EXISTS userrole")
