"""How an uploaded file becomes a book.

One path for every way a file arrives (the upload form, a bulk upload,
an import from an OPDS catalog) and every format we take. Whatever the
format, the book the rest of the app reads is an EPUB at ``file_path``;
a format that is converted keeps what was uploaded at ``original_path``
for download.

Files and rows are made in that order and unmade together: a file that
cannot be read, a row that cannot be written or a commit that fails
leaves nothing on disk.
"""

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app import errors
from app.models.book import Book
from app.models.library import LibraryBook
from app.models.user import User, UserRole
from app.services.access import get_accessible_library
from app.services.book_files import book_files
from app.services.cbz2epub import CbzError, convert_cbz_to_epub
from app.services.epub_parser import extract_cover, parse_epub_metadata
from app.services.mobi2epub import DrmProtectedError, convert_mobi_to_epub
from app.services.partial_md5 import compute_partial_md5
from app.services.storage import (
    delete_file,
    get_book_path,
    get_cover_path,
    save_upload_file,
)
from app.services.txt2epub import (
    EmptyTextError,
    convert_txt_to_epub,
    detect_language,
)
from app.services.zh_epub import sample_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Recipe:
    """What one format needs on its way to being a book."""

    # Said to the uploader when the file cannot be read as this format.
    invalid: str
    # Makes the EPUB from what was uploaded (source, epub, title hint).
    # None: the upload is the EPUB.
    convert: Callable[[str, str, str], None] | None = None
    # Whether the EPUB may carry a cover to take out.
    cover: bool = True
    # Whether to sample the text for Simplified Chinese.
    script: bool = True
    # Columns this format always sets.
    fields: dict[str, Any] = field(default_factory=dict)


def _from_mobi(source: str, epub: str, _hint: str) -> None:
    convert_mobi_to_epub(source, epub)


def _from_cbz(source: str, epub: str, _hint: str) -> None:
    convert_cbz_to_epub(source, epub)


_MOBI = _Recipe(invalid="Invalid MOBI file", convert=_from_mobi)

_RECIPES: dict[str, _Recipe] = {
    ".epub": _Recipe(invalid="Invalid EPUB file"),
    # (A TXT has no cover; its title comes from the file's name.)
    ".txt": _Recipe(
        invalid="Invalid TXT file", convert=convert_txt_to_epub, cover=False
    ),
    ".mobi": _MOBI,
    ".azw3": _MOBI,
    # A comic has no text: it is classified an image book here, so the
    # text pipeline never picks it up.
    ".cbz": _Recipe(
        invalid="Invalid CBZ file",
        convert=_from_cbz,
        script=False,
        fields={"word_count": 0, "is_image_book": True},
    ),
}

UPLOAD_SUFFIXES = tuple(_RECIPES)


def upload_suffix(file: UploadFile) -> str | None:
    """The upload's extension when it is one we take, else None."""
    suffix = Path(file.filename or "").suffix.lower()
    return suffix if suffix in _RECIPES else None


def require_upload_permission(user: User) -> None:
    if user.role != UserRole.admin and not user.can_upload:
        raise HTTPException(status_code=403, detail="Upload permission required")


async def validate_upload_library(
    library_id: str | None, user: User, db: AsyncSession
) -> uuid.UUID:
    """Parse and authorize the target library BEFORE any file hits disk."""

    # Every book must belong to a library: every listing (flat/grouped/search/
    # random) reaches books through library membership, so a library-less
    # book would be invisible to everyone — including its uploader.
    if not library_id:
        raise HTTPException(status_code=422, detail="library_id is required")
    try:
        lib_id = uuid.UUID(library_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid library id") from None
    library = await get_accessible_library(lib_id, user, db)
    if library.calibre_path:
        raise errors.CALIBRE_NO_UPLOAD()
    return lib_id


def _is_simplified(file_path: str) -> bool:
    """Whether the book's text reads as Simplified Chinese — by its
    characters, not its declared language, which is often wrong. Such a
    book is reported in the upload response and the uploader is asked
    whether to convert it: never converted unasked."""
    try:
        return detect_language(sample_text(file_path), "utf-8") == "zh-CN"
    except Exception:
        logger.exception("Could not sample %s for its script", file_path)
        return False


def _rejection(exc: Exception, recipe: _Recipe) -> HTTPException | None:
    """What the uploader is told, when the reason is one we know how to
    say. ``None`` otherwise: they hear only "not a file of this kind" and
    the rest goes to the log."""
    if isinstance(exc, EmptyTextError):
        return errors.TXT_EMPTY()
    if isinstance(exc, DrmProtectedError):
        return errors.UPLOAD_DRM()
    if isinstance(exc, CbzError):
        return HTTPException(status_code=400, detail=str(exc))
    return None


async def ingest_upload(
    file: UploadFile, user: User, lib_id: uuid.UUID | None, db: AsyncSession
) -> Book:
    """Save one upload and stage its Book row (no commit — see
    ``commit_ingested``). A file that cannot be made into a book is
    refused with a 400 and leaves nothing on disk."""
    suffix = upload_suffix(file) or ".epub"
    recipe = _RECIPES[suffix]
    book_id = uuid.uuid4()

    if recipe.convert:
        original_path = get_book_path(book_id, f"book{suffix}")
        file_path = get_book_path(book_id, "book.epub")
    else:
        original_path = None
        file_path = get_book_path(book_id, file.filename or "book.epub")
    cover_path = get_cover_path(book_id) if recipe.cover else None
    made = [p for p in (original_path, file_path, cover_path) if p]

    def discard() -> None:
        for path in made:
            delete_file(path)

    await save_upload_file(file, original_path or file_path)
    try:
        # Conversion and parsing are blocking zip/XML work — kept off the
        # event loop (a bulk upload would otherwise stall every request).
        if recipe.convert:
            await asyncio.to_thread(
                recipe.convert,
                original_path,
                file_path,
                Path(file.filename or "").stem,
            )
        simplified = (
            await asyncio.to_thread(_is_simplified, file_path)
            if recipe.script
            else None
        )
        metadata = await asyncio.to_thread(parse_epub_metadata, file_path)
        cover_ok = bool(cover_path) and await asyncio.to_thread(
            extract_cover, file_path, cover_path
        )
        digest = await asyncio.to_thread(compute_partial_md5, file_path)
        size = os.path.getsize(file_path)
    except Exception as exc:
        rejection = _rejection(exc, recipe)
        if rejection is None:
            logger.exception("Upload rejected (%s): %s", recipe.invalid, file.filename)
            rejection = HTTPException(status_code=400, detail=recipe.invalid)
        discard()
        raise rejection from exc

    book = Book(
        id=book_id,
        file_path=file_path,
        file_size=size,
        format=suffix[1:],
        original_path=original_path,
        cover_path=cover_path if cover_ok else None,
        partial_md5=digest,
        added_by=user.id,
        **recipe.fields,
        **metadata,
    )
    if simplified is not None:
        book.zh_simplified = simplified
    try:
        db.add(book)
        await db.flush()
        if lib_id:
            db.add(LibraryBook(library_id=lib_id, book_id=book_id, added_by=user.id))
    except Exception:
        discard()
        raise
    return book


def discard_ingested(books: list[Book]) -> None:
    """Remove the files of books that were staged and will not be kept."""
    for book in books:
        for path in book_files(book):
            delete_file(path)


async def commit_ingested(db: AsyncSession, books: list[Book]) -> None:
    """Keep the staged books: commit, then start the work that follows
    an upload. A commit that fails takes the files with it."""
    # (Imported here: the tasks import the services.)
    from app.tasks.metadata import fetch_book_metadata
    from app.tasks.text_extract import extract_book_text

    # (Read now: a failed commit leaves the rows unreadable.)
    paths = [path for book in books for path in book_files(book)]
    try:
        await db.commit()
    except Exception:
        for path in paths:
            delete_file(path)
        raise
    for book in books:
        await db.refresh(book)
        extract_book_text.delay(str(book.id))
        fetch_book_metadata.delay(str(book.id))
