"""One-off: read the language of every uploaded EPUB-backed book again.

The library took the first <dc:language> of the package. It now takes the
language of the text when the text is plainly Chinese or Japanese and no
declared language says so (app.services.epub_parser.book_language): tools
stamp "en" on books they know nothing about, and a package may list
several. Only the file can tell, so this opens each one. Books in a
Calibre library are left alone — their metadata is Calibre's.

--dry-run lists every change in a read-only transaction; nothing is
written.

Usage: docker compose exec backend uv run python -m scripts.redetect_languages
       [--dry-run]
"""

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def main(dry_run: bool) -> None:
    from sqlalchemy import text, update

    from app.database import create_task_engine
    from app.models.book import Book
    from app.services.epub_parser import book_language
    from app.vendor.ebooklib import epub

    def language(path: str) -> str | None:
        book = epub.read_epub(path, options={"ignore_ncx": True, "ignore_images": True})
        declared = [value for value, _ in book.get_metadata("DC", "language") or []]
        return book_language(declared, path)

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            if dry_run:
                await db.execute(text("SET TRANSACTION READ ONLY"))
            result = await db.execute(
                text(
                    "SELECT id, file_path, epub_language,"
                    " coalesce(title, epub_title) FROM books"
                    " WHERE file_path IS NOT NULL AND calibre_id IS NULL"
                    " AND NOT coalesce(is_image_book, false) ORDER BY id"
                )
            )
            rows = result.fetchall()
            logger.info("%d books%s", len(rows), " (dry run)" * dry_run)

            changed = 0
            failed = 0
            for book_id, path, old, title in rows:
                try:
                    new = await asyncio.to_thread(language, path)
                except Exception as e:
                    failed += 1
                    logger.warning("  unreadable %s (%s): %s", book_id, title, e)
                    continue
                if new == old:
                    continue
                changed += 1
                logger.info("  %s  %s → %s  %s", book_id, old, new, title)
                if not dry_run:
                    await db.execute(
                        update(Book).where(Book.id == book_id).values(epub_language=new)
                    )
            if not dry_run:
                await db.commit()
            logger.info(
                "Done: %d books, %d %s, %d unreadable.",
                len(rows),
                changed,
                "would change" if dry_run else "changed",
                failed,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="list the changes, write nothing"
    )
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
