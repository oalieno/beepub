"""One-off: re-encode stored covers at the canonical 800px / q85.

Covers synced from Calibre used to be copied at full size. This
walks the covers directory and rewrites each oversized cover in place
through the same encoder new covers go through.

Same path, same file name, and the file keeps its mtime (the Calibre
re-sync compares it against Calibre's cover), so nothing in the database
changes; a browser holding the old bytes keeps showing the same picture.
A cover is only rewritten when the result is at least 10% smaller, which
also makes a second run a no-op. Each write goes to a temp file and is
renamed into place, so interrupting it is safe and a rerun resumes.

Usage: docker compose exec backend uv run python -m scripts.recompress_covers
       [--dry-run] [--dir /data/covers]
"""

import argparse
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# Already canonical-sized and this small: not worth decoding at all.
SMALL_BYTES = 200 * 1024
# The saving a rewrite has to buy; re-encoding our own output buys ~0.
MIN_SAVING = 0.10
PROGRESS_EVERY = 1000
TMP_SUFFIX = ".recompress"


def recompress(path: Path, dry_run: bool = False) -> int | None:
    """Rewrite one cover if that shrinks it; the bytes saved, or None
    when it was left alone."""
    from PIL import Image

    from app.services.storage import COVER_MAX_WIDTH, encode_cover

    before = path.stat()
    if before.st_size <= SMALL_BYTES:
        with Image.open(path) as img:
            if img.width <= COVER_MAX_WIDTH:
                return None
    data = path.read_bytes()
    encoded = encode_cover(data)
    if len(encoded) > len(data) * (1 - MIN_SAVING):
        return None
    if dry_run:
        return len(data) - len(encoded)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    tmp.write_bytes(encoded)
    os.utime(tmp, ns=(before.st_atime_ns, before.st_mtime_ns))
    # Replaced (a new upload, a Calibre re-sync) while we were encoding:
    # the new cover wins.
    if path.stat().st_mtime_ns != before.st_mtime_ns:
        tmp.unlink()
        return None
    os.replace(tmp, path)
    return len(data) - len(encoded)


def run(covers_dir: Path, dry_run: bool = False) -> tuple[int, int, int, int]:
    """(covers seen, rewritten, failed, bytes saved)."""
    seen = rewritten = failed = saved = 0
    for entry in os.scandir(covers_dir):
        if entry.name.endswith(TMP_SUFFIX):
            # Left by an interrupted run.
            Path(entry.path).unlink(missing_ok=True)
            continue
        if not entry.is_file() or not entry.name.endswith(".jpg"):
            continue
        seen += 1
        try:
            gained = recompress(Path(entry.path), dry_run)
        except Exception as e:
            failed += 1
            logger.warning("  skipped %s: %s", entry.name, e)
            gained = None
        if gained is not None:
            rewritten += 1
            saved += gained
        if seen % PROGRESS_EVERY == 0:
            logger.info(
                "  %d covers, %d rewritten, %.1f MB saved",
                seen,
                rewritten,
                saved / 1e6,
            )
    return seen, rewritten, failed, saved


def main() -> None:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=settings.covers_dir)
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be saved"
    )
    args = parser.parse_args()

    logger.info(
        "Recompressing covers in %s%s...", args.dir, " (dry run)" * args.dry_run
    )
    seen, rewritten, failed, saved = run(Path(args.dir), args.dry_run)
    logger.info(
        "Done: %d covers, %d rewritten, %d unreadable, %.1f MB saved.",
        seen,
        rewritten,
        failed,
        saved / 1e6,
    )


if __name__ == "__main__":
    main()
