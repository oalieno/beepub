"""scripts.find_orphan_files — what counts as a file no book owns."""

import os
import uuid
from pathlib import Path

from scripts.find_orphan_files import find_orphans

HOUR = 3600


def _write(path: Path, *, age: float, now: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (now - age, now - age))
    return path


def test_only_old_unowned_files_named_like_ours_are_orphans(tmp_path):
    now = 1_800_000_000.0
    books, covers = tmp_path / "books", tmp_path / "covers"
    owned, lost, fresh = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    kept = [
        _write(books / f"{owned}.epub", age=9 * HOUR, now=now),
        _write(books / f"{owned}.original.epub", age=9 * HOUR, now=now),
        _write(covers / f"{owned}.jpg", age=9 * HOUR, now=now),
        _write(covers / "thumb" / f"{owned}.jpg.webp", age=9 * HOUR, now=now),
    ]
    orphans = [
        _write(books / f"{lost}.epub", age=9 * HOUR, now=now),
        _write(books / f"{lost}.epub.{'ab' * 16}.tmp", age=9 * HOUR, now=now),
        _write(covers / f"{lost}.jpg.tmp-1a2b3c4d", age=9 * HOUR, now=now),
        _write(covers / "thumb" / f"{lost}.jpg.webp", age=9 * HOUR, now=now),
    ]
    # An upload still on its way in: on disk, not yet in the database.
    _write(books / f"{fresh}.epub", age=60, now=now)
    # Somebody else's files in our directories are not ours to judge.
    strangers = [
        _write(covers / f"{owned}.jpg.bak-bars", age=9 * HOUR, now=now),
        _write(books / "notes.txt", age=9 * HOUR, now=now),
    ]
    # Nothing below the directories themselves (and `thumb`) is looked at.
    _write(books / "deeper" / f"{lost}.epub", age=9 * HOUR, now=now)

    found = find_orphans(
        [books, covers, tmp_path / "missing"],
        {str(p) for p in kept},
        now=now,
        grace_seconds=HOUR,
    )

    assert found.orphans == sorted(p.resolve() for p in orphans)
    assert found.not_ours == sorted(p.resolve() for p in strangers)
    assert found.in_use == len(kept)
    assert found.too_new == 1
    assert found.orphan_bytes == len(orphans)
