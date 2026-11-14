import asyncio
import json
import logging
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.database import create_task_engine
from app.models.book import Book
from app.models.library import Library, LibraryBook
from app.services.book_files import invalidate_derived_text
from app.services.partial_md5 import compute_partial_md5
from app.services.storage import (
    delete_file,
    get_book_path,
    get_cover_path,
    save_cover_bytes,
)
from app.tasks.text_extract import extract_book_text

logger = logging.getLogger(__name__)

SYNC_KEY_PREFIX = "beepub:calibre:sync"

# Safety margin when comparing Calibre's per-book last_modified (written
# by the machine running Calibre) against our last_synced_at (server
# clock). Books stamped inside the margin just take the normal slow path.
CALIBRE_CLOCK_SKEW = timedelta(minutes=10)


def get_metadata_db_mtime(calibre_path: str) -> datetime | None:
    """Get metadata.db mtime as UTC datetime."""
    db_path = os.path.join(calibre_path, "metadata.db")
    try:
        return datetime.fromtimestamp(os.path.getmtime(db_path), tz=UTC)
    except OSError:
        return None


@dataclass
class CalibreBookInfo:
    calibre_id: int
    title: str
    authors: list[str]
    publisher: str | None
    description: str | None
    published_date: str | None
    isbn: str | None
    series: str | None
    series_index: float | None
    tags: list[str] | None
    epub_path: str  # full path to .epub file
    cover_path: str | None  # full path to cover.jpg or None
    file_size: int
    added_at: str | None  # Calibre timestamp (when added to Calibre)
    last_modified: str | None  # Calibre timestamp (last change to this book)


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)


def scan_calibre_libraries(base_dir: str = "/calibre") -> list[dict]:
    """Scan a Calibre root directory for libraries containing metadata.db."""
    results = []
    if not os.path.isdir(base_dir):
        return results
    # Accept a single library mounted directly at base_dir (the common
    # `-v ~/Calibre:/calibre:ro` case) as well as libraries in subfolders.
    candidates = [base_dir] + [
        os.path.join(base_dir, entry) for entry in sorted(os.listdir(base_dir))
    ]
    for lib_path in candidates:
        db_path = os.path.join(lib_path, "metadata.db")
        if os.path.isdir(lib_path) and os.path.isfile(db_path):
            # Count EPUB books
            try:
                count = _count_calibre_epubs(db_path)
            except Exception:
                count = None
            results.append(
                {
                    "path": lib_path,
                    "name": os.path.basename(lib_path.rstrip("/")),
                    "book_count": count,
                }
            )
    return results


def _copy_cover(src: str, dest: str) -> bool:
    """Bring a Calibre cover over as the canonical (downscaled) JPEG. The
    copy keeps Calibre's mtime, as copy2 did: the re-sync check compares
    the two to spot a cover changed in Calibre."""
    # Via a temp file, so a cover Calibre can't hand over intact never
    # costs the book the one it already has.
    tmp = f"{dest}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        with open(src, "rb") as f:
            data = f.read()
        if not save_cover_bytes(data, tmp):
            return False
        st = os.stat(src)
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, dest)
        return True
    except Exception:
        delete_file(tmp)
        return False


def _count_calibre_epubs(db_path: str) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(DISTINCT b.id) FROM books b "
            "JOIN data d ON d.book = b.id AND UPPER(d.format) = 'EPUB'"
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


def read_calibre_books(calibre_dir: str) -> list[CalibreBookInfo]:
    """Read all EPUB books from a Calibre library's metadata.db."""
    db_path = os.path.join(calibre_dir, "metadata.db")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                b.id AS calibre_id,
                b.title,
                b.path AS book_path,
                b.has_cover,
                b.pubdate,
                b.timestamp AS added_at,
                b.last_modified,
                b.series_index,
                d.name AS file_name,
                d.uncompressed_size AS file_size,
                GROUP_CONCAT(DISTINCT a.name) AS authors,
                p.name AS publisher,
                c.text AS description,
                i.val AS isbn,
                s.name AS series_name,
                GROUP_CONCAT(DISTINCT t.name) AS tags
            FROM books b
            JOIN data d ON d.book = b.id AND UPPER(d.format) = 'EPUB'
            LEFT JOIN books_authors_link bal ON bal.book = b.id
            LEFT JOIN authors a ON a.id = bal.author
            LEFT JOIN comments c ON c.book = b.id
            LEFT JOIN books_publishers_link bpl ON bpl.book = b.id
            LEFT JOIN publishers p ON p.id = bpl.publisher
            LEFT JOIN identifiers i ON i.book = b.id AND i.type = 'isbn'
            LEFT JOIN books_series_link bsl ON bsl.book = b.id
            LEFT JOIN series s ON s.id = bsl.series
            LEFT JOIN books_tags_link btl ON btl.book = b.id
            LEFT JOIN tags t ON t.id = btl.tag
            GROUP BY b.id
        """)
        results = []
        for row in cur.fetchall():
            epub_path = os.path.join(
                calibre_dir, row["book_path"], f"{row['file_name']}.epub"
            )
            cover = None
            if row["has_cover"]:
                cover = os.path.join(calibre_dir, row["book_path"], "cover.jpg")

            authors_str = row["authors"] or ""
            authors = [a.strip() for a in authors_str.split(",") if a.strip()]

            pub_date = None
            if row["pubdate"]:
                pd = str(row["pubdate"])
                # Calibre stores dates like "2024-01-15T00:00:00+00:00"
                # Only keep date part if it looks valid (not 0101-01-01)
                if not pd.startswith("0101"):
                    pub_date = pd[:10] if len(pd) >= 10 else pd

            added_at_str = None
            if row["added_at"]:
                added_at_str = str(row["added_at"])

            series_name = row["series_name"]
            series_index_val = row["series_index"] if series_name else None

            tags_str = row["tags"] or ""
            tags_list = [t.strip() for t in tags_str.split(",") if t.strip()] or None

            results.append(
                CalibreBookInfo(
                    calibre_id=row["calibre_id"],
                    title=row["title"],
                    authors=authors,
                    publisher=row["publisher"],
                    description=row["description"],
                    published_date=pub_date,
                    isbn=row["isbn"],
                    series=series_name,
                    series_index=series_index_val,
                    tags=tags_list,
                    epub_path=epub_path,
                    cover_path=cover,
                    file_size=row["file_size"] or 0,
                    added_at=added_at_str,
                    last_modified=(
                        str(row["last_modified"]) if row["last_modified"] else None
                    ),
                )
            )
        return results
    finally:
        conn.close()


def _parse_calibre_timestamp(ts: str | None) -> datetime | None:
    """Parse a Calibre timestamp string into a datetime object."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _calibre_row_unchanged(
    last_modified: str | None,
    epub_mtime: datetime | None,
    previous_synced_at: datetime | None,
) -> bool:
    """Fast-path check: Calibre stamps last_modified on every change it
    makes to a book (metadata, covers, files), so a row older than our
    previous sync — minus clock skew, since the stamp comes from the
    machine running Calibre — can't have anything new for us. Books
    without a stored epub_mtime still need the slow path once to
    backfill it. Out-of-band edits (not through Calibre) are already
    unsupported."""
    if previous_synced_at is None or epub_mtime is None:
        return False
    cal_modified = _parse_calibre_timestamp(last_modified)
    if cal_modified is None:
        return False
    if cal_modified.tzinfo is None:
        cal_modified = cal_modified.replace(tzinfo=UTC)
    return cal_modified < previous_synced_at - CALIBRE_CLOCK_SKEW


def _sync_key(library_id: uuid.UUID) -> str:
    return f"{SYNC_KEY_PREFIX}:{library_id}"


async def get_sync_status(library_id: uuid.UUID) -> dict | None:
    """Get current sync status from Redis."""
    client = aioredis.from_url(settings.redis_url)
    try:
        data = await client.get(_sync_key(library_id))
        if data:
            return json.loads(data)
        return None
    finally:
        await client.aclose()


async def sync_calibre_library(
    calibre_dir: str,
    library_id: uuid.UUID,
    admin_user_id: uuid.UUID,
    then_copy: bool = False,
) -> None:
    """Background task: sync a Calibre library into BeePub. With
    ``then_copy`` the books are then copied in and the library cut loose
    from Calibre (linking in "copy" mode): one run, one progress report."""
    client = aioredis.from_url(settings.redis_url)
    key = _sync_key(library_id)
    # A library being copied in is about to stop being Calibre's: a sync
    # in the middle would be working on rows that are changing hands.
    if await client.exists(_copy_lock_key(library_id)):
        logger.info(f"Library {library_id} is being copied in, sync skipped")
        await client.aclose()
        return

    async def _update_progress(
        result: SyncResult, total: int, processed: int, status: str = "running"
    ):
        progress = {
            "status": status,
            "total": total,
            "processed": processed,
            "added": result.added,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "skipped": result.skipped,
            "removed": result.removed,
            "errors": result.errors[-10:],  # keep last 10 errors
            "started_at": progress_started_at,
        }
        await client.set(key, json.dumps(progress), ex=3600)  # expire in 1 hour

    progress_started_at = datetime.now(UTC).isoformat()

    result = SyncResult()
    try:
        # Read Calibre books in a thread (synchronous SQLite)
        calibre_books = await asyncio.to_thread(read_calibre_books, calibre_dir)
        total = len(calibre_books)
        await _update_progress(result, total, 0)

        async with (
            create_task_engine() as (_engine, SessionLocal),
            SessionLocal() as db,
        ):
            # Verify library still exists (may have been deleted)
            from sqlalchemy import select

            lib_check = await db.execute(
                select(Library).where(Library.id == library_id)
            )
            library = lib_check.scalar_one_or_none()
            if not library:
                logger.info(f"Library {library_id} was deleted, aborting sync")
                await _update_progress(result, total, 0, "failed")
                return
            previous_synced_at = library.last_synced_at

            # Get existing books in this library by calibre_id
            existing_query = (
                select(Book)
                .join(LibraryBook, LibraryBook.book_id == Book.id)
                .where(LibraryBook.library_id == library_id)
                .where(Book.calibre_id.isnot(None))
            )
            existing_result = await db.execute(existing_query)
            existing_books = {b.calibre_id: b for b in existing_result.scalars().all()}

            new_book_ids: list[str] = []
            re_extract_book_ids: list[str] = []

            for i, cal_book in enumerate(calibre_books):
                try:
                    if cal_book.calibre_id in existing_books:
                        book = existing_books[cal_book.calibre_id]

                        # Fast path — skips the per-book file stats, which
                        # dominate cold-cache sync time on large libraries.
                        if _calibre_row_unchanged(
                            cal_book.last_modified,
                            book.epub_mtime,
                            previous_synced_at,
                        ):
                            result.unchanged += 1
                            if (i + 1) % 500 == 0:
                                await _update_progress(result, total, i + 1)
                            continue

                        # Update existing book
                        changed = False
                        if book.file_path != cal_book.epub_path:
                            book.file_path = cal_book.epub_path
                            changed = True
                        if book.epub_title != cal_book.title:
                            book.epub_title = cal_book.title
                            changed = True
                        if book.epub_authors != cal_book.authors:
                            book.epub_authors = cal_book.authors
                            changed = True
                        calibre_added = _parse_calibre_timestamp(cal_book.added_at)
                        if book.calibre_added_at != calibre_added:
                            book.calibre_added_at = calibre_added
                            changed = True
                        if book.epub_series != cal_book.series:
                            book.epub_series = cal_book.series
                            changed = True
                        if book.epub_series_index != cal_book.series_index:
                            book.epub_series_index = cal_book.series_index
                            changed = True
                        if book.epub_tags != cal_book.tags:
                            book.epub_tags = cal_book.tags
                            changed = True

                        # Detect EPUB content edits in Calibre (xhtml/cover
                        # changes inside the zip). When the file's mtime
                        # advances past the stored value, wipe extracted text
                        # chunks and re-dispatch extraction so search/AI
                        # features see the new content.
                        if os.path.exists(cal_book.epub_path):
                            current_epub_mtime = datetime.fromtimestamp(
                                os.path.getmtime(cal_book.epub_path), tz=UTC
                            )
                            if (
                                book.epub_mtime is None
                                or current_epub_mtime > book.epub_mtime
                            ):
                                if book.epub_mtime is not None:
                                    # File changed since last sync — drop stale
                                    # chunks and reset derived flags so the
                                    # re-extract task runs cleanly.
                                    await invalidate_derived_text(db, book)
                                    re_extract_book_ids.append(str(book.id))
                                book.epub_mtime = current_epub_mtime
                                # Calibre rewrites the EPUB on metadata edits,
                                # which changes KOReader's document digest.
                                book.partial_md5 = await asyncio.to_thread(
                                    compute_partial_md5, cal_book.epub_path
                                )
                                changed = True

                        # Re-sync cover if Calibre's cover is newer than ours,
                        # or if we don't have one yet but Calibre does.
                        if cal_book.cover_path and os.path.exists(cal_book.cover_path):
                            dest = book.cover_path or get_cover_path(book.id)
                            src_mtime = os.path.getmtime(cal_book.cover_path)
                            dest_mtime = (
                                os.path.getmtime(dest) if os.path.exists(dest) else 0
                            )
                            if src_mtime > dest_mtime:
                                copied = await asyncio.to_thread(
                                    _copy_cover, cal_book.cover_path, dest
                                )
                                if copied:
                                    book.cover_path = dest
                                    # Force-dirty even when path is unchanged so
                                    # updated_at advances and the ?v= cache-buster
                                    # on the cover URL changes.
                                    flag_modified(book, "cover_path")
                                    changed = True

                        if changed:
                            result.updated += 1
                        else:
                            result.unchanged += 1
                    else:
                        # New book — verify EPUB exists
                        if not os.path.exists(cal_book.epub_path):
                            result.skipped += 1
                            result.errors.append(
                                f"EPUB not found: {cal_book.epub_path}"
                            )
                            await _update_progress(result, total, i + 1)
                            continue

                        book_id = uuid.uuid4()

                        # Use Calibre metadata directly (skip EPUB parsing for speed)
                        epub_meta = {
                            "epub_title": cal_book.title,
                            "epub_authors": cal_book.authors,
                            "epub_publisher": cal_book.publisher,
                            "epub_description": cal_book.description,
                            "epub_published_date": cal_book.published_date,
                            "epub_isbn": cal_book.isbn,
                            "epub_series": cal_book.series,
                            "epub_series_index": cal_book.series_index,
                            "epub_tags": cal_book.tags,
                        }

                        cover_dest = None
                        if cal_book.cover_path and os.path.exists(cal_book.cover_path):
                            dest = get_cover_path(book_id)
                            copied = await asyncio.to_thread(
                                _copy_cover, cal_book.cover_path, dest
                            )
                            if copied:
                                cover_dest = dest

                        calibre_added = _parse_calibre_timestamp(cal_book.added_at)
                        epub_mtime = datetime.fromtimestamp(
                            os.path.getmtime(cal_book.epub_path), tz=UTC
                        )

                        book = Book(
                            id=book_id,
                            file_path=cal_book.epub_path,
                            file_size=cal_book.file_size,
                            format="epub",
                            cover_path=cover_dest,
                            calibre_id=cal_book.calibre_id,
                            calibre_added_at=calibre_added,
                            epub_mtime=epub_mtime,
                            partial_md5=await asyncio.to_thread(
                                compute_partial_md5, cal_book.epub_path
                            ),
                            added_by=admin_user_id,
                            **epub_meta,
                        )
                        db.add(book)

                        lb = LibraryBook(
                            library_id=library_id,
                            book_id=book_id,
                            added_by=admin_user_id,
                        )
                        db.add(lb)
                        new_book_ids.append(str(book_id))
                        result.added += 1

                except Exception as e:
                    result.skipped += 1
                    result.errors.append(f"Error processing '{cal_book.title}': {e}")
                    logger.exception(
                        f"Error syncing calibre book {cal_book.calibre_id}"
                    )

                # Update progress every book
                await _update_progress(result, total, i + 1)

            # Remove orphan books — in DB but no longer in Calibre
            calibre_ids = {cb.calibre_id for cb in calibre_books}
            orphans = [b for cid, b in existing_books.items() if cid not in calibre_ids]
            if orphans:
                for book in orphans:
                    # Remove library association
                    orphan_lb = await db.execute(
                        select(LibraryBook).where(
                            LibraryBook.library_id == library_id,
                            LibraryBook.book_id == book.id,
                        )
                    )
                    for lb in orphan_lb.scalars().all():
                        await db.delete(lb)
                    # Delete cover file if exists
                    if book.cover_path:
                        delete_file(book.cover_path)
                    await db.delete(book)
                    result.removed += 1
                logger.info(
                    f"Removed {result.removed} orphan books from library {library_id}"
                )

            # Update last_synced_at
            from sqlalchemy import update

            await db.execute(
                update(Library)
                .where(Library.id == library_id)
                .values(last_synced_at=datetime.now(UTC))
            )

            await db.commit()

        # Dispatch text extraction tasks AFTER commit
        for book_id in new_book_ids:
            extract_book_text.delay(book_id)
        for book_id in re_extract_book_ids:
            extract_book_text.delay(book_id)

        # Auto-start metadata backfill if new books were added
        if new_book_ids:
            from app.tasks.metadata import auto_start_backfill

            auto_start_backfill()

        if then_copy:
            await copy_calibre_library(library_id)
        else:
            await _update_progress(result, total, total, "completed")

    except Exception as e:
        result.errors.append(f"Sync failed: {e}")
        logger.exception("Calibre sync failed")
        try:
            await _update_progress(result, 0, 0, "failed")
        except Exception:
            pass
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


# --- Copying a Calibre library in -------------------------------------------
#
# A linked library reads its books from Calibre's folder. Copying it in
# makes it an ordinary BeePub library: every book's file is copied to
# BeePub's storage and the rows are cut loose from Calibre. The rows are
# the same ones, so progress, highlights, shelves and overrides stay; the
# bytes are the same, so ``partial_md5`` (KOReader's key) stays too.
#
# Nothing in the database changes until every file is across: files are
# copied first, to paths named after the book's id, then one transaction
# repoints the rows and unlinks the library. A run cut short leaves only
# files behind, which the next run finds and does not copy again.

COPY_LOCK_PREFIX = "beepub:calibre:copy"
# Refreshed with every book, so a run that died frees the library soon.
COPY_LOCK_TTL = 900
# Room left on the disk after the copy.
COPY_FREE_MARGIN = 256 * 1024 * 1024
# Titles reported back when files cannot be read.
COPY_UNREADABLE_SHOWN = 100


def _copy_lock_key(library_id: uuid.UUID) -> str:
    return f"{COPY_LOCK_PREFIX}:{library_id}"


async def copy_in_progress(library_id: uuid.UUID) -> bool:
    client = aioredis.from_url(settings.redis_url)
    try:
        return bool(await client.exists(_copy_lock_key(library_id)))
    finally:
        await client.aclose()


async def mark_queued(library_id: uuid.UUID, mode: str) -> None:
    """A run handed to the worker reads as running from the start: the
    page polling it would otherwise see nothing and stop looking."""
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.set(
            _sync_key(library_id),
            json.dumps(
                {
                    "mode": mode,
                    "status": "running",
                    "total": 0,
                    "processed": 0,
                    "added": 0,
                    "updated": 0,
                    "unchanged": 0,
                    "skipped": 0,
                    "removed": 0,
                    "errors": [],
                    "started_at": datetime.now(UTC).isoformat(),
                }
            ),
            ex=3600,
        )
    finally:
        await client.aclose()


def _copy_destination(book: Book) -> str:
    return get_book_path(book.id, os.path.basename(book.file_path or "book.epub"))


def _copied_already(src: str, dest: str) -> bool:
    try:
        return os.path.getsize(dest) == os.path.getsize(src)
    except OSError:
        return False


def _copy_book_file(src: str, dest: str) -> None:
    """Copy via a temp file: a half-written book never has the real name."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = f"{dest}.part"
    try:
        shutil.copy2(src, tmp)
        if os.path.getsize(tmp) != os.path.getsize(src):
            raise OSError("copy is not the size of its source")
        os.replace(tmp, dest)
    except BaseException:
        delete_file(tmp)
        raise


def _copy_plan(books: list[Book]) -> dict:
    """What copying these books in takes: bytes still to copy, room on
    the disk, and the books whose files cannot be read."""
    needed = 0
    unreadable: list[Book] = []
    for book in books:
        src = book.file_path
        if not src or not os.path.isfile(src):
            unreadable.append(book)
        elif not _copied_already(src, _copy_destination(book)):
            needed += os.path.getsize(src)
    os.makedirs(settings.books_dir, exist_ok=True)
    return {
        "bytes_needed": needed,
        "bytes_free": shutil.disk_usage(settings.books_dir).free,
        "unreadable": unreadable,
    }


async def _calibre_books_of(db, library_id: uuid.UUID) -> list[Book]:
    from sqlalchemy import select

    result = await db.execute(
        select(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(LibraryBook.library_id == library_id)
        .where(Book.calibre_id.isnot(None))
        .order_by(Book.created_at, Book.id)
    )
    return list(result.scalars().all())


async def copy_preview(db, library_id: uuid.UUID) -> dict:
    """For the confirmation: how many books, how much room they take and
    how much there is."""
    books = await _calibre_books_of(db, library_id)
    plan = await asyncio.to_thread(_copy_plan, books)
    return {
        "book_count": len(books),
        "bytes_needed": plan["bytes_needed"],
        "bytes_free": plan["bytes_free"],
        "unreadable_count": len(plan["unreadable"]),
    }


async def copy_calibre_library(
    library_id: uuid.UUID, skip_unreadable: bool = False
) -> None:
    """Background task: copy a linked library's books in and unlink it.

    Books whose files cannot be read stop the run before anything is
    changed, and are named in the status; ``skip_unreadable`` goes ahead
    without them — they are removed, as a sync removes a book Calibre no
    longer has."""
    from sqlalchemy import select

    client = aioredis.from_url(settings.redis_url)
    key = _sync_key(library_id)
    lock = _copy_lock_key(library_id)
    started_at = datetime.now(UTC).isoformat()

    async def report(status: str, total: int, processed: int, **extra) -> None:
        progress = {
            "mode": "copy",
            "status": status,
            "total": total,
            "processed": processed,
            "added": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
            "removed": 0,
            "errors": [],
            "started_at": started_at,
            **extra,
        }
        await client.set(key, json.dumps(progress), ex=3600)

    try:
        if not await client.set(lock, "1", nx=True, ex=COPY_LOCK_TTL):
            return
        try:
            async with (
                create_task_engine() as (_engine, SessionLocal),
                SessionLocal() as db,
            ):
                library = (
                    await db.execute(select(Library).where(Library.id == library_id))
                ).scalar_one_or_none()
                if library is None or not library.calibre_path:
                    await report("failed", 0, 0, errors=["Not a Calibre library"])
                    return
                books = await _calibre_books_of(db, library_id)
                total = len(books)
                await report("running", total, 0)

                plan = await asyncio.to_thread(_copy_plan, books)
                unreadable: list[Book] = plan["unreadable"]
                if unreadable and not skip_unreadable:
                    await report(
                        "failed",
                        total,
                        0,
                        reason="unreadable",
                        unreadable=[
                            b.display_title or ""
                            for b in unreadable[:COPY_UNREADABLE_SHOWN]
                        ],
                        unreadable_count=len(unreadable),
                    )
                    return
                if plan["bytes_needed"] + COPY_FREE_MARGIN > plan["bytes_free"]:
                    await report(
                        "failed",
                        total,
                        0,
                        reason="space",
                        bytes_needed=plan["bytes_needed"],
                        bytes_free=plan["bytes_free"],
                    )
                    return

                gone = {b.id for b in unreadable}
                copied: list[tuple[Book, str]] = []
                for i, book in enumerate(books):
                    if book.id not in gone:
                        dest = _copy_destination(book)
                        if not _copied_already(book.file_path, dest):
                            await asyncio.to_thread(
                                _copy_book_file, book.file_path, dest
                            )
                        copied.append((book, dest))
                    await client.expire(lock, COPY_LOCK_TTL)
                    await report("running", total, i + 1)

                # Every file is across: the rows change hands together.
                covers: list[str] = []
                for book, dest in copied:
                    book.file_path = dest
                    book.file_size = os.path.getsize(dest)
                    book.calibre_id = None
                for book in unreadable:
                    links = await db.execute(
                        select(LibraryBook).where(LibraryBook.book_id == book.id)
                    )
                    for link in links.scalars().all():
                        await db.delete(link)
                    if book.cover_path:
                        covers.append(book.cover_path)
                    await db.delete(book)
                library.calibre_path = None
                library.auto_sync = False
                await db.commit()
                for path in covers:
                    delete_file(path)

            await report("completed", total, total, removed=len(unreadable))
        except Exception as e:
            logger.exception("Copying a Calibre library in failed")
            try:
                await report("failed", 0, 0, errors=[str(e)])
            except Exception:
                pass
        finally:
            await client.delete(lock)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
