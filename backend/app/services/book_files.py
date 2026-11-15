"""What a book's row owns on disk and in the tables derived from its file."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.book_text import BookTextChunk


def book_files(book: Book) -> list[str]:
    """The files a book's row owns: to be removed, after the commit, when
    the row is deleted. A Calibre book's own file is on a read-only mount
    and stays; a physical book has no file at all."""
    paths = []
    if book.calibre_id is None and book.file_path:
        paths.append(book.file_path)
    if book.original_path:
        paths.append(book.original_path)
    if book.cover_path:
        paths.append(book.cover_path)
    return paths


async def invalidate_derived_text(db: AsyncSession, book: Book) -> None:
    """The book's file has changed: what was extracted from the old one —
    text chunks, and with them the summaries and passage vectors — is
    dropped and the flags that say it exists are reset, so the extraction
    asked for next starts clean instead of finding chunks and stopping.
    The caller commits, then enqueues `extract_book_text`."""
    await db.execute(
        BookTextChunk.__table__.delete().where(BookTextChunk.book_id == book.id)
    )
    book.has_text = False
    book.is_summarized = False
    book.has_embedding = False
    book.word_count = None
    book.is_image_book = None


def require_book_file(book: Book) -> None:
    """A physical book (format="physical") has no file behind it: asking
    for one is a 409, not a missing file."""
    if book.file_path is None:
        raise HTTPException(
            status_code=409, detail="This is a physical book — it has no file"
        )
