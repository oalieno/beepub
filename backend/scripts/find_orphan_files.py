"""Find (and, when asked, remove) stored files that no book owns.

An upload that failed part-way, a book deleted while its files could not
be, a conversion that was interrupted: each could leave a file in the
data directories with no row pointing at it. Uploads no longer leave any
behind, but nothing ever looked for the ones already there. This does.

It walks the books, covers and illustrations directories and holds every
file against what the database says is in use — each book's file, its
kept original, its cover and that cover's thumbnail, each illustration's
image.

By default it only reports. With ``--delete`` it removes what it found.
Three things keep it from removing something it should not:

- Only files named the way BeePub names them are candidates. Anything
  else in those directories is listed as "not ours" and left alone.
- A file changed within the last hour is skipped (``--grace-minutes``):
  an upload writes its files before its row is committed.
- A Calibre library's own files live outside these directories and are
  never looked at.

Usage: docker compose exec backend uv run python -m scripts.find_orphan_files
       [--delete] [--grace-minutes 60] [--list 50]
"""

import argparse
import asyncio
import functools
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# `<id>.<ext>`, `<id>.original.epub`, `<id>.jpg.webp` — and the temporary
# files written beside them (`<id>.jpg.tmp-1a2b3c4d`, `<id>.epub.<hex>.tmp`).
_OURS = re.compile(
    rf"^{_UUID}(\.[a-z0-9]+){{1,2}}(\.tmp(-[0-9a-f]+)?)?$", re.IGNORECASE
)


@dataclass
class Found:
    orphans: list[Path] = field(default_factory=list)
    orphan_bytes: int = 0
    not_ours: list[Path] = field(default_factory=list)
    too_new: int = 0
    in_use: int = 0


def _files(directory: str):
    """The files directly in a directory, and in its `thumb` beside them
    (where cover thumbnails are kept). Nothing deeper, no symlinks."""
    for entry in os.scandir(directory):
        if entry.is_file(follow_symlinks=False):
            yield entry
        elif entry.name == "thumb" and entry.is_dir(follow_symlinks=False):
            for inner in os.scandir(entry.path):
                if inner.is_file(follow_symlinks=False):
                    yield inner


def _resolved(path: str) -> str:
    """A path with its directory resolved once — not once per file: a
    library is tens of thousands of files, often on a network disk."""
    directory, name = os.path.split(path)
    return os.path.join(_real_directory(directory), name)


@functools.cache
def _real_directory(directory: str) -> str:
    return os.path.realpath(directory)


def find_orphans(
    directories: list[Path], in_use: set[str], *, now: float, grace_seconds: float
) -> Found:
    """Hold what is on disk against what is in use. A file in use costs
    no disk access beyond the directory listing it came from."""
    used = {_resolved(p) for p in in_use}
    found = Found()
    for directory in directories:
        if not directory.is_dir():
            continue
        for entry in _files(os.path.realpath(directory)):
            if entry.path in used:
                found.in_use += 1
            elif not _OURS.match(entry.name):
                found.not_ours.append(Path(entry.path))
            else:
                stat = entry.stat(follow_symlinks=False)
                if now - stat.st_mtime < grace_seconds:
                    found.too_new += 1
                else:
                    found.orphans.append(Path(entry.path))
                    found.orphan_bytes += stat.st_size
    found.orphans.sort()
    found.not_ours.sort()
    return found


async def paths_in_use() -> set[str]:
    """Every file path the database refers to."""
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.book import Book
    from app.models.illustration import Illustration
    from app.services.storage import cover_thumbnail_path

    used: set[str] = set()
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Book.file_path, Book.original_path, Book.cover_path)
        )
        for file_path, original_path, cover_path in rows:
            used.update(p for p in (file_path, original_path, cover_path) if p)
            if cover_path:
                used.add(cover_thumbnail_path(cover_path))
        used.update((await db.execute(select(Illustration.image_path))).scalars())
    return used


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def main() -> None:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--delete", action="store_true", help="remove what is found")
    parser.add_argument("--grace-minutes", type=float, default=60)
    parser.add_argument("--list", type=int, default=50, help="how many to print")
    args = parser.parse_args()

    directories = [
        Path(settings.books_dir),
        Path(settings.covers_dir),
        Path(settings.illustrations_dir),
    ]
    found = find_orphans(
        directories,
        asyncio.run(paths_in_use()),
        now=time.time(),
        grace_seconds=args.grace_minutes * 60,
    )

    print(f"in use: {found.in_use}")
    print(f"skipped as recently changed: {found.too_new}")
    print(f"not ours, left alone: {len(found.not_ours)}")
    for path in found.not_ours[: args.list]:
        print(f"  {path}")
    print(f"orphans: {len(found.orphans)} ({_size(found.orphan_bytes)})")
    for path in found.orphans[: args.list]:
        print(f"  {path}")
    if len(found.orphans) > args.list:
        print(f"  … and {len(found.orphans) - args.list} more")

    if not args.delete:
        if found.orphans:
            print("Nothing was removed. Run again with --delete to remove them.")
        return
    removed = 0
    for path in found.orphans:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            print(f"  could not remove {path}: {exc}")
    print(f"removed: {removed}")


if __name__ == "__main__":
    main()
