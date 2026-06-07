"""Scope series identity per library.

Series have no entity table — they are identified by the normalised series name
``lower(btrim(coalesce(series, epub_series)))``. That key was global across all
libraries, so the same name in two libraries (a light novel and its manga
adaptation) merged into one series. Identity becomes ``(library_id, series_key)``:

- ``user_series_interactions`` gains ``library_id`` in its primary key. Existing
  rows fan out to every library that contains a book with that series name.
- ``bookshelf_books`` series rows gain ``library_id``; they fan out the same way.

Rows whose series name maps to no library are dropped (orphans).

Revision ID: 042
Revises: 041
Create Date: 2026-06-07
"""

import sqlalchemy as sa

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- user_series_interactions: add library_id to the primary key ----------
    # Rebuild the table so each (user, series_key) rating fans out to every
    # library containing a book with that normalised series name.
    op.create_table(
        "user_series_interactions_new",
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "library_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("libraries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("series_key", sa.String(500), primary_key=True),
        sa.Column("series_name", sa.String(500), nullable=False),
        sa.Column("rating", sa.Numeric(2, 1), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute("""
        INSERT INTO user_series_interactions_new
            (user_id, library_id, series_key, series_name, rating, notes, updated_at)
        SELECT DISTINCT
            usi.user_id, lb.library_id, usi.series_key,
            usi.series_name, usi.rating, usi.notes, usi.updated_at
        FROM user_series_interactions usi
        JOIN books b
            ON lower(btrim(coalesce(b.series, b.epub_series))) = usi.series_key
        JOIN library_books lb ON lb.book_id = b.id
    """)
    op.drop_table("user_series_interactions")
    op.rename_table("user_series_interactions_new", "user_series_interactions")

    # --- bookshelf_books: add library_id to series rows ----------------------
    op.add_column(
        "bookshelf_books",
        sa.Column(
            "library_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("libraries.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # First library (by id) for the existing surrogate row, plus the old check
    # constraint must go before a series row can hold a library_id.
    op.drop_constraint(
        "ck_bookshelf_books_one_target", "bookshelf_books", type_="check"
    )
    op.drop_index("uq_bookshelf_books_series", table_name="bookshelf_books")

    op.execute("""
        UPDATE bookshelf_books bb
        SET library_id = sub.library_id
        FROM (
            SELECT bb2.id AS row_id, MIN(lb.library_id::text)::uuid AS library_id
            FROM bookshelf_books bb2
            JOIN books b
                ON lower(btrim(coalesce(b.series, b.epub_series))) = bb2.series_key
            JOIN library_books lb ON lb.book_id = b.id
            WHERE bb2.series_key IS NOT NULL
            GROUP BY bb2.id
        ) sub
        WHERE bb.id = sub.row_id
    """)
    # Fan out series rows whose name is in more than one library: clone the row
    # (fresh id) for every additional library.
    op.execute("""
        INSERT INTO bookshelf_books
            (id, bookshelf_id, book_id, series_key, library_id, sort_order, added_at)
        SELECT
            gen_random_uuid(), bb.bookshelf_id, NULL, bb.series_key,
            extra.library_id, bb.sort_order, bb.added_at
        FROM bookshelf_books bb
        JOIN (
            SELECT bb2.id AS row_id, lb.library_id
            FROM bookshelf_books bb2
            JOIN books b
                ON lower(btrim(coalesce(b.series, b.epub_series))) = bb2.series_key
            JOIN library_books lb ON lb.book_id = b.id
            WHERE bb2.series_key IS NOT NULL
            GROUP BY bb2.id, lb.library_id
        ) extra ON extra.row_id = bb.id
        WHERE bb.series_key IS NOT NULL
          AND bb.library_id IS DISTINCT FROM extra.library_id
    """)
    # Drop orphan series rows (name maps to no accessible library).
    op.execute(
        "DELETE FROM bookshelf_books WHERE series_key IS NOT NULL"
        " AND library_id IS NULL"
    )

    op.create_check_constraint(
        "ck_bookshelf_books_one_target",
        "bookshelf_books",
        "(book_id IS NOT NULL AND series_key IS NULL AND library_id IS NULL)"
        " <> (series_key IS NOT NULL AND library_id IS NOT NULL"
        " AND book_id IS NULL)",
    )
    op.create_index(
        "uq_bookshelf_books_series",
        "bookshelf_books",
        ["bookshelf_id", "library_id", "series_key"],
        unique=True,
        postgresql_where=sa.text("series_key IS NOT NULL"),
    )


def downgrade() -> None:
    # --- bookshelf_books: collapse back to a name-only series key -------------
    op.drop_index("uq_bookshelf_books_series", table_name="bookshelf_books")
    op.drop_constraint(
        "ck_bookshelf_books_one_target", "bookshelf_books", type_="check"
    )
    # Collapse fan-out duplicates: keep the lowest id per (shelf, series_key).
    op.execute("""
        DELETE FROM bookshelf_books a
        USING bookshelf_books b
        WHERE a.series_key IS NOT NULL
          AND a.series_key = b.series_key
          AND a.bookshelf_id = b.bookshelf_id
          AND a.id > b.id
    """)
    op.drop_column("bookshelf_books", "library_id")
    op.create_check_constraint(
        "ck_bookshelf_books_one_target",
        "bookshelf_books",
        "(book_id IS NOT NULL) <> (series_key IS NOT NULL)",
    )
    op.create_index(
        "uq_bookshelf_books_series",
        "bookshelf_books",
        ["bookshelf_id", "series_key"],
        unique=True,
        postgresql_where=sa.text("series_key IS NOT NULL"),
    )

    # --- user_series_interactions: collapse back to (user_id, series_key) -----
    op.create_table(
        "user_series_interactions_old",
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("series_key", sa.String(500), primary_key=True),
        sa.Column("series_name", sa.String(500), nullable=False),
        sa.Column("rating", sa.Numeric(2, 1), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # One row per (user, series_key): pick the most recently updated.
    op.execute("""
        INSERT INTO user_series_interactions_old
            (user_id, series_key, series_name, rating, notes, updated_at)
        SELECT DISTINCT ON (user_id, series_key)
            user_id, series_key, series_name, rating, notes, updated_at
        FROM user_series_interactions
        ORDER BY user_id, series_key, updated_at DESC
    """)
    op.drop_table("user_series_interactions")
    op.rename_table("user_series_interactions_old", "user_series_interactions")
