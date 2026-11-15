"""A book's bytes: the file itself, what is inside it (chapters, images,
the page list), its cover, and rewriting it as Traditional Chinese.

Same ``/api/books`` prefix as the rest (the URLs predate the split).
"""

import asyncio
import logging
import mimetypes
import os
import re
import shutil
import uuid
import zipfile
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import errors
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book
from app.models.reading import Highlight
from app.models.user import User, UserRole
from app.schemas.book import (
    BookCoverUpdate,
    BookOut,
    ZhConversionPreview,
    ZhConversionRequest,
    ZhConversionSegment,
)
from app.services.access import (
    get_accessible_book,
)
from app.services.background import enqueue_after_commit
from app.services.book_files import (
    invalidate_derived_text,
    require_book_file,
)
from app.services.epub_pages import read_page_manifest
from app.services.epub_parser import parse_epub_metadata
from app.services.ingest import (
    require_upload_permission,
)
from app.services.partial_md5 import compute_partial_md5
from app.services.storage import (
    MAX_COVER_DOWNLOAD_SIZE,
    cover_thumbnail_path,
    cover_url_allowed,
    delete_file,
    download_cover,
    get_cover_path,
    get_kept_epub_path,
    place_cover,
    save_cover_bytes,
)
from app.services.zh_epub import (
    Quote,
    convert_epub,
    convert_highlight,
    preview,
    section_of,
)
from app.tasks.text_extract import extract_book_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("/{book_id}/file")
async def get_book_file(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role != UserRole.admin and not current_user.can_download:
        raise errors.DOWNLOAD_PERMISSION_REQUIRED()
    book = await get_accessible_book(book_id, current_user, db)
    require_book_file(book)
    if not os.path.exists(book.file_path):
        raise errors.FILE_NOT_FOUND()
    # Set filename for browser download
    title = book.title or book.epub_title or "book"
    filename = f"{title}.epub"
    return FileResponse(
        book.file_path,
        media_type="application/epub+zip",
        filename=filename,
    )


async def _convertible_book(book_id: uuid.UUID, user: User, db: AsyncSession) -> Book:
    require_upload_permission(user)
    book = await get_accessible_book(book_id, user, db)
    if book.is_image_book or not book.file_path or not os.path.exists(book.file_path):
        raise HTTPException(status_code=409, detail="This book has no text to convert")
    # A Calibre library's files are Calibre's: never rewritten here.
    if book.calibre_id is not None:
        raise HTTPException(
            status_code=409, detail="Books in a Calibre library cannot be converted"
        )
    return book


def _live_highlights(book_id: uuid.UUID):
    return select(Highlight).where(
        Highlight.book_id == book_id, Highlight.deleted_at.is_(None)
    )


@router.get("/{book_id}/zh-conversion", response_model=ZhConversionPreview)
async def preview_book_zh(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """What converting the book would do: a sentence of it, piece by piece
    under both modes (none when nothing would change), and how many
    highlights — every reader's, since the file is shared — go along."""
    book = await _convertible_book(book_id, current_user, db)
    segments = await asyncio.to_thread(preview, book.file_path)
    count = await db.scalar(
        select(func.count()).select_from(_live_highlights(book.id).subquery())
    )
    return ZhConversionPreview(
        segments=[ZhConversionSegment(**vars(s)) for s in segments]
        if segments
        else None,
        highlights=count or 0,
    )


@router.post("/{book_id}/zh-conversion", response_model=BookOut)
async def convert_book_zh(
    book_id: uuid.UUID,
    body: ZhConversionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Rewrite the book's EPUB as Traditional Chinese, whatever script it
    was detected as, since the reader asked. The first conversion keeps the
    file as it was (an EPUB upload has no other copy). Highlights are
    carried over: each one's quote is cut from the converted text, so the
    reader re-finds the ones whose offsets moved."""
    book = await _convertible_book(book_id, current_user, db)
    # One conversion of a book at a time: a second request waits here, and
    # then sees what the first one did (the kept original above all).
    await db.execute(select(Book.id).where(Book.id == book.id).with_for_update())
    await db.refresh(book)
    file_path = book.file_path
    tmp_path = f"{file_path}.{uuid.uuid4().hex}.tmp"
    try:
        result = await asyncio.to_thread(convert_epub, file_path, tmp_path, body.mode)
        metadata = await asyncio.to_thread(parse_epub_metadata, tmp_path)
    except Exception:
        logger.exception("Conversion failed: %s", book.id)
        delete_file(tmp_path)
        raise HTTPException(
            status_code=400, detail="The book could not be converted"
        ) from None
    if not result.changed:
        delete_file(tmp_path)
        return book
    if not book.original_path:
        original_path = get_kept_epub_path(book.id)
        # (Never over a copy already kept: that one is the original.)
        if not os.path.exists(original_path):
            await asyncio.to_thread(shutil.copyfile, file_path, original_path)
        book.original_path = original_path
    os.replace(tmp_path, file_path)
    book.file_size = os.path.getsize(file_path)
    book.partial_md5 = await asyncio.to_thread(compute_partial_md5, file_path)
    for key in _CONVERTED_METADATA:
        setattr(book, key, metadata.get(key))
    now = datetime.now(UTC)
    book.updated_at = now
    for highlight in (await db.scalars(_live_highlights(book.id))).all():
        quote = convert_highlight(
            Quote(highlight.text, highlight.prefix, highlight.suffix),
            result,
            section_of(highlight.cfi_range, highlight.section_index),
            body.mode,
        )
        if (quote.text, quote.prefix, quote.suffix) != (
            highlight.text,
            highlight.prefix,
            highlight.suffix,
        ):
            highlight.text = quote.text
            highlight.prefix = quote.prefix
            highlight.suffix = quote.suffix
            # Devices pull highlights newer than theirs.
            highlight.updated_at = now
    # The text extracted from the file as it was — search, the companion's
    # quotes, summaries, vectors — is of the old script: extracted anew.
    await invalidate_derived_text(db, book)
    await db.commit()
    await db.refresh(book)
    enqueue_after_commit(extract_book_text, str(book.id))
    return book


# What conversion rewrites in the package metadata.
_CONVERTED_METADATA = (
    "epub_title",
    "epub_authors",
    "epub_publisher",
    "epub_language",
    "epub_description",
    "epub_series",
    "epub_tags",
)


@router.get("/{book_id}/original")
async def get_book_original(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The file as it was uploaded, for books converted at ingest
    (format txt/mobi/azw3/cbz). /file stays the EPUB everything else reads."""
    if current_user.role != UserRole.admin and not current_user.can_download:
        raise errors.DOWNLOAD_PERMISSION_REQUIRED()
    book = await get_accessible_book(book_id, current_user, db)
    if not book.original_path or not os.path.exists(book.original_path):
        raise HTTPException(status_code=404, detail="Original file not found")
    suffix = Path(book.original_path).suffix
    title = book.title or book.epub_title or "book"
    # octet-stream on purpose: a text/* type would get a charset=utf-8
    # appended, and the source may be Big5 or GBK.
    return FileResponse(
        book.original_path,
        media_type="application/octet-stream",
        filename=f"{title}{suffix}",
    )


@router.get("/{book_id}/content/{path:path}")
async def get_book_content(
    book_id: uuid.UUID,
    path: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Serve individual files from within the EPUB zip (the reader streams a book through it)."""
    book = await get_accessible_book(book_id, current_user, db)
    require_book_file(book)
    if not os.path.exists(book.file_path):
        raise errors.FILE_NOT_FOUND()

    # ETag based on EPUB mtime + path. When Calibre rewrites the EPUB
    # (cover/xhtml edits), mtime advances and the ETag changes, so the
    # browser's cached copy is invalidated naturally.
    epub_mtime = int(os.path.getmtime(book.file_path))
    # (A checksum, not hash(): that one differs in every process, and
    # a restart would make every reader fetch its chapters again.)
    etag = f'"{epub_mtime:x}-{zlib.crc32(path.encode()):x}"'
    # A book's own files are another author's, served from this site's
    # address. Opened by their URL they must not become a page of the
    # site: one that runs scripts would run them as the reader signed in.
    # `sandbox` leaves anything opened that way without scripts and
    # without the site's origin; the reader, which fetches them and shows
    # them in its own frames, is not affected.
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=86400, must-revalidate",
        "Content-Security-Policy": "sandbox",
        "X-Content-Type-Options": "nosniff",
    }

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    try:
        # Zip decompression + regex rewrite are blocking CPU/disk work and
        # this endpoint fires on every chapter turn — keep it off the event
        # loop so concurrent readers don't serialize behind each other.
        data = await asyncio.to_thread(_read_epub_entry, book.file_path, path)
    except KeyError:
        raise errors.PATH_NOT_IN_EPUB() from None
    content_type, _ = mimetypes.guess_type(path)
    # A chapter is not sent as a page at all (the reader goes by the
    # book's own manifest, not by this header).
    if content_type is None or content_type in _DOCUMENT_TYPES:
        content_type = "application/octet-stream"

    return Response(
        content=data,
        media_type=content_type,
        headers=headers,
    )


_DOCUMENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def _read_epub_entry(file_path: str, path: str) -> bytes:
    with zipfile.ZipFile(file_path, "r") as zf:
        try:
            data = zf.read(path)
        except KeyError:
            # A book made on a case-insensitive file system may name a file
            # "style/a.css" that the zip holds as "Style/a.css".
            folded = {n.lower(): n for n in zf.namelist()}
            if path.lower() not in folded:
                raise
            data = zf.read(folded[path.lower()])

    # Fix malformed XHTML: self-close void elements (e.g. <link ...> → <link .../>)
    if path.endswith((".xhtml", ".html", ".htm")):
        text = data.decode("utf-8", errors="replace")
        text = re.sub(
            r"<(meta|link|br|hr|img|input|source|col|area|base|embed|track|wbr)"
            r"(\s[^>]*?)(?<!/)>",
            r"<\1\2/>",
            text,
        )
        data = text.encode("utf-8")
    return data


@router.get("/{book_id}/images")
async def list_epub_images(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all images embedded in the EPUB file."""
    book = await get_accessible_book(book_id, current_user, db)
    require_book_file(book)
    if not os.path.exists(book.file_path):
        raise errors.FILE_NOT_FOUND()
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    def scan() -> list[dict]:
        with zipfile.ZipFile(book.file_path, "r") as zf:
            return [
                {"path": name, "name": os.path.basename(name)}
                for name in sorted(zf.namelist())
                if os.path.splitext(name)[1].lower() in image_exts
            ]

    return await asyncio.to_thread(scan)


@router.get("/{book_id}/pages")
async def get_book_pages(
    book_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The EPUB's spine as pages: each entry names the image the page
    shows, its pixel size and spread hint, in reading order with the
    book's page-progression direction. Image pagers read this instead of
    laying the XHTML out; /images is sorted by file name and is not it."""
    book = await get_accessible_book(book_id, current_user, db)
    require_book_file(book)
    if not os.path.exists(book.file_path):
        raise errors.FILE_NOT_FOUND()

    epub_mtime = int(os.path.getmtime(book.file_path))
    etag = f'"{epub_mtime:x}-pages"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=86400, must-revalidate",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    try:
        manifest = await asyncio.to_thread(read_page_manifest, book.file_path)
    except Exception:
        raise HTTPException(
            status_code=422, detail="Could not read the EPUB spine"
        ) from None
    return JSONResponse(content=manifest.to_dict(), headers=headers)


@router.get("/{book_id}/cover")
async def get_book_cover(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    size: Literal["full", "thumb"] = Query("full"),
):
    """The cover, for clients that cannot use the static path (the app
    sends a token, not a cookie). ``size=thumb`` is the small one the
    lists show — the full cover where a book has none yet."""
    book = await get_accessible_book(book_id, current_user, db)
    if not book.cover_path or not os.path.exists(book.cover_path):
        raise errors.COVER_NOT_FOUND()
    if size == "thumb":
        thumbnail = cover_thumbnail_path(book.cover_path)
        if os.path.exists(thumbnail):
            return FileResponse(thumbnail, media_type="image/webp")
    return FileResponse(book.cover_path, media_type="image/jpeg")


@router.put("/{book_id}/cover", response_model=BookOut)
async def update_book_cover(
    book_id: uuid.UUID,
    body: BookCoverUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Replace the cover from an allowlisted source URL. The download
    lands in a temp file first so a failure can't destroy the cover the
    book already has."""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise errors.BOOK_NOT_FOUND()
    if not cover_url_allowed(body.url):
        raise HTTPException(status_code=422, detail="cover url host is not allowed")
    dest = get_cover_path(book_id)
    tmp = f"{dest}.tmp-{uuid.uuid4().hex[:8]}"
    if not await download_cover(body.url, tmp):
        raise HTTPException(status_code=502, detail="Cover download failed")
    place_cover(tmp, dest)
    book.cover_path = dest
    # Same path as the old cover: bump the stamp the cover URL is keyed
    # on, or browsers keep showing the cached image.
    book.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(book)
    return book


@router.post("/{book_id}/cover", response_model=BookOut)
async def upload_book_cover(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise errors.BOOK_NOT_FOUND()
    data = await file.read()
    if len(data) > MAX_COVER_DOWNLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Cover image too large")
    dest = get_cover_path(book_id)
    tmp = f"{dest}.tmp-{uuid.uuid4().hex[:8]}"
    if not save_cover_bytes(data, tmp):
        raise HTTPException(status_code=422, detail="Not a decodable image")
    place_cover(tmp, dest)
    book.cover_path = dest
    # Same path as the old cover: bump the stamp the cover URL is keyed
    # on, or browsers keep showing the cached image.
    book.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(book)
    return book
