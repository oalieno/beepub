import asyncio
import json
import logging
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as aioredis

from app.config import settings
from app.database import create_task_engine
from app.models.book import Book
from app.models.library import Library, LibraryBook
from app.services.storage import get_cover_path
from app.tasks.text_extract import extract_book_text

logger = logging.getLogger(__name__)

SYNC_KEY_PREFIX = "beepub:calibre:sync"


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
    for entry in sorted(os.listdir(base_dir)):
        lib_path = os.path.join(base_dir, entry)
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
                    "name": entry,
                    "book_count": count,
                }
            )
    return results


def _copy_cover(src: str, dest: str) -> bool:
    """Copy a cover file directly without resizing."""
    try:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return True
    except Exception:
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
) -> None:
    """Background task: sync a Calibre library into BeePub."""
    client = aioredis.from_url(settings.redis_url)
    key = _sync_key(library_id)

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
            if not lib_check.scalar_one_or_none():
                logger.info(f"Library {library_id} was deleted, aborting sync")
                await _update_progress(result, total, 0, "failed")
                return

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

            for i, cal_book in enumerate(calibre_books):
                try:
                    if cal_book.calibre_id in existing_books:
                        # Update existing book
                        book = existing_books[cal_book.calibre_id]
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

                        # Copy cover directly (skip Pillow resize — Calibre covers are already reasonable)
                        cover_dest = None
                        if cal_book.cover_path and os.path.exists(cal_book.cover_path):
                            dest = get_cover_path(book_id)
                            copied = await asyncio.to_thread(
                                _copy_cover, cal_book.cover_path, dest
                            )
                            if copied:
                                cover_dest = dest

                        calibre_added = _parse_calibre_timestamp(cal_book.added_at)

                        book = Book(
                            id=book_id,
                            file_path=cal_book.epub_path,
                            file_size=cal_book.file_size,
                            format="epub",
                            cover_path=cover_dest,
                            calibre_id=cal_book.calibre_id,
                            calibre_added_at=calibre_added,
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
                from app.services.storage import delete_file

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

        # Auto-start metadata backfill if new books were added
        if new_book_ids:
            from app.tasks.metadata import auto_start_backfill

            auto_start_backfill()

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
