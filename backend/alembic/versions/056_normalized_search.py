"""beepub_norm() + normalized trigram indexes for fuzzy book search

Plain ILIKE (044) requires a contiguous substring match, so an extra
space, a fullwidth variant, or one wrong character returns nothing.
beepub_norm() folds a string for matching: strip all whitespace, drop
title punctuation (both widths), map fullwidth alphanumerics to ASCII,
lowercase. Searching compares beepub_norm(query) against beepub_norm
(column) — both sides folded by the same SQL function, so there is no
Python twin to drift out of sync. (Postgres has no NFKC; the translate
map covers the fullwidth ASCII block, which is the practical CJK case.
This intentionally diverges from the Python-side NFKC in
plugins/metadata/base.py.)

The expression indexes serve both the tier-2 normalized ILIKE and the
tier-3 trigram operators (<%). ISBN stays exact-match only.

Revision ID: 056
Revises: 055
"""

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

_FULLWIDTH = (
    "".join(chr(0xFF10 + i) for i in range(10))  # ０-９
    + "".join(chr(0xFF21 + i) for i in range(26))  # Ａ-Ｚ
    + "".join(chr(0xFF41 + i) for i in range(26))  # ａ-ｚ
)
_HALFWIDTH = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
# translate() drops FROM-characters that have no TO-counterpart: title
# punctuation in both widths vanishes from the folded string.
_DELETED = (
    "，、。；：！？·・‧（）【】《》〈〉「」『』〔〕［］｛｝～－—–‐…．＇＂"
    ",.;:!?()[]{}<>~-_/\\|'\"“”‘’"
)

NORM_INDEXES = {
    "title": "beepub_norm(title)",
    "epub_title": "beepub_norm(epub_title)",
    "series": "beepub_norm(series)",
    "epub_series": "beepub_norm(epub_series)",
    "authors": "beepub_norm(beepub_join_authors(authors))",
    "epub_authors": "beepub_norm(beepub_join_authors(epub_authors))",
}


def upgrade() -> None:
    frm = (_FULLWIDTH + _DELETED).replace("'", "''")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION beepub_norm(text)
        RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE RETURNS NULL ON NULL INPUT
        AS $beepub$
        SELECT lower(translate(
            regexp_replace($1, '[\\s　]+', '', 'g'),
            '{frm}',
            '{_HALFWIDTH}'
        ))
        $beepub$
        """
    )
    for name, expr in NORM_INDEXES.items():
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_books_{name}_norm_trgm "
            f"ON books USING gin (({expr}) gin_trgm_ops)"
        )


def downgrade() -> None:
    for name in NORM_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS ix_books_{name}_norm_trgm")
    op.execute("DROP FUNCTION IF EXISTS beepub_norm(text)")
