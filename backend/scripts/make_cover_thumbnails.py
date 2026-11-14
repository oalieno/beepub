"""One-off: make the small cover every stored cover is missing.

Covers saved from now on get a thumbnail as they are written (see
`write_cover_thumbnail`); this walks the covers directory and makes the
ones for covers that were there before. Until it has run, the lists
simply show the full cover where a thumbnail is asked for.

A cover that already has a thumbnail at least as new as itself is left
alone, so a second run does nothing and an interrupted one resumes.

Usage: docker compose exec backend uv run python -m scripts.make_cover_thumbnails
       [--dir /data/covers]
"""

import argparse
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

PROGRESS_EVERY = 1000


def run(covers_dir: Path) -> tuple[int, int, int]:
    """(covers seen, thumbnails made, failed)."""
    from app.services.storage import cover_thumbnail_path, write_cover_thumbnail

    seen = made = failed = 0
    for entry in os.scandir(covers_dir):
        if not entry.is_file() or not entry.name.endswith(".jpg"):
            continue
        seen += 1
        thumbnail = Path(cover_thumbnail_path(entry.path))
        try:
            fresh = (
                thumbnail.exists()
                and thumbnail.stat().st_mtime_ns >= entry.stat().st_mtime_ns
            )
        except OSError:
            fresh = False
        if not fresh:
            if write_cover_thumbnail(entry.path):
                made += 1
            else:
                failed += 1
                logger.warning("  no thumbnail for %s", entry.name)
        if seen % PROGRESS_EVERY == 0:
            logger.info("  %d covers, %d thumbnails made", seen, made)
    return seen, made, failed


def main() -> None:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=settings.covers_dir)
    args = parser.parse_args()
    seen, made, failed = run(Path(args.dir))
    logger.info("%d covers, %d thumbnails made, %d failed", seen, made, failed)


if __name__ == "__main__":
    main()
