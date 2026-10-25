"""One-off: class the short text books again by the picture-page rule.

The library called a book an image book when it had under 500 words.
It now calls one an image book when at least 80% of its linear spine
items are picture pages (app.services.epub_text.SpinePictures), which
only the file can tell: a picture page has no text chunk. This opens the
file of every book still classed text with under 5000 words and sets
is_image_book on those the rule finds image books. Books already classed
image books (CBZ imports, pure-image EPUBs) are not touched, and no book
is turned from an image book into text.

--dry-run lists every candidate and what the rule makes of it, in a
read-only transaction; nothing is written.

Usage: docker compose exec backend uv run python -m scripts.reclassify_image_books
       [--dry-run]
"""

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# Text novels are far above this; the manga it is for are ~580-1700.
MAX_WORDS = 5000


async def main(dry_run: bool) -> None:
    from sqlalchemy import text, update

    from app.database import create_task_engine
    from app.models.book import Book
    from app.services.epub_text import count_picture_pages
    from app.vendor.ebooklib import epub

    def classify(path: str):
        book = epub.read_epub(path, options={"ignore_ncx": True, "ignore_images": True})
        return count_picture_pages(book)

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            if dry_run:
                await db.execute(text("SET TRANSACTION READ ONLY"))
            result = await db.execute(
                text(
                    "SELECT id, file_path, word_count, format,"
                    " coalesce(title, epub_title) FROM books"
                    " WHERE is_image_book = false AND word_count < :max"
                    " AND file_path IS NOT NULL ORDER BY word_count, id"
                ),
                {"max": MAX_WORDS},
            )
            rows = result.fetchall()
            logger.info(
                "%d candidates (is_image_book false, under %d words)%s",
                len(rows),
                MAX_WORDS,
                " (dry run)" * dry_run,
            )

            flips = []
            failed = 0
            for book_id, path, words, fmt, title in rows:
                try:
                    pictures = await asyncio.to_thread(classify, path)
                except Exception as e:
                    failed += 1
                    logger.warning("  unreadable %s (%s): %s", book_id, title, e)
                    continue
                image = pictures.is_image_book
                logger.info(
                    "  %s  %5d words  %3d/%-3d picture pages  %-5s  %s  %s",
                    book_id,
                    words,
                    pictures.pictures,
                    pictures.linear,
                    fmt,
                    "IMAGE" if image else "text ",
                    title,
                )
                if image:
                    flips.append(book_id)

            if not dry_run and flips:
                await db.execute(
                    update(Book).where(Book.id.in_(flips)).values(is_image_book=True)
                )
                await db.commit()
            logger.info(
                "Done: %d candidates, %d %s image books, %d unreadable.",
                len(rows),
                len(flips),
                "would become" if dry_run else "made",
                failed,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="list the candidates, write nothing"
    )
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
