"""Duplicate edition detection for book-to-Work grouping.

Normalization pipeline:
  raw title → full-width→half-width → lowercase → strip punctuation
  raw authors → sort → lowercase

Matching: group by exact (normalized_title, normalized_first_author, series_index),
  2+ books = candidate group.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book

logger = logging.getLogger(__name__)

# Punctuation to strip (keep CJK characters and alphanumeric)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_title(title: str) -> str:
    """Normalize a book title for exact duplicate matching.

    Keeps the full title (no subtitle stripping) so that
    "影宅 (第39話)" and "影宅 (第27話)" remain distinct keys.
    """
    try:
        # Full-width to half-width (NFKC normalization)
        title = unicodedata.normalize("NFKC", title)
        # Lowercase
        title = title.lower()
        # Strip punctuation
        title = _PUNCT_RE.sub("", title)
        # Collapse whitespace
        title = " ".join(title.split())
        return title.strip()
    except Exception:
        logger.warning("Failed to normalize title: %r", title, exc_info=True)
        return title.lower().strip() if title else ""


def normalize_authors(authors: list[str] | None) -> str:
    """Normalize authors list into a single comparable string."""
    if not authors:
        return ""
    try:
        normalized = sorted(a.lower().strip() for a in authors if a)
        return "|".join(normalized)
    except Exception:
        logger.warning("Failed to normalize authors: %r", authors, exc_info=True)
        return ""


async def find_duplicate_groups(
    db: AsyncSession,
) -> tuple[list[dict], int, bool]:
    """Find potential duplicate edition groups via exact title+author matching.

    Returns (groups, total_books_scanned, truncated).
    Each group is a dict with 'books' list and 'match_method'.
    """
    # Load all books that are NOT already in a Work
    result = await db.execute(
        select(
            Book.id,
            Book.title,
            Book.epub_title,
            Book.authors,
            Book.epub_authors,
            Book.cover_path,
            Book.epub_isbn,
            Book.metadata_count,
            Book.created_at,
            Book.work_id,
            Book.series_index,
            Book.epub_series_index,
        ).where(Book.work_id.is_(None))
    )
    rows = result.all()
    total_scanned = len(rows)

    # Build normalized groups (no subtitle stripping for exact match)
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        display_title = row.title or row.epub_title
        display_authors = row.authors or row.epub_authors
        if not display_title:
            continue

        norm_title = normalize_title(display_title)
        norm_author = (
            normalize_authors(display_authors).split("|")[0] if display_authors else ""
        )
        # Include series_index in key so different volumes don't collide
        series_idx = row.series_index or row.epub_series_index
        idx_key = str(series_idx) if series_idx is not None else ""
        key = (norm_title, norm_author, idx_key)

        groups[key].append(
            {
                "id": row.id,
                "display_title": display_title,
                "display_authors": display_authors,
                "cover_path": row.cover_path,
                "epub_isbn": row.epub_isbn,
                "metadata_count": row.metadata_count,
                "created_at": row.created_at,
            }
        )

    # Filter to groups with 2+ books, sort by group size descending
    result_groups = [
        {"books": books, "match_method": "exact"}
        for books in groups.values()
        if len(books) >= 2
    ]
    result_groups.sort(key=lambda g: len(g["books"]), reverse=True)
    return result_groups, total_scanned, False
