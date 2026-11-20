"""Make the small cover every stored cover is missing, now.

The worker does this by itself each time it starts (app/tasks/covers.py),
in the background. This is the same walk, run in the foreground — to
watch it, or for a covers directory the worker does not see.

A cover that already has a thumbnail at least as new as itself is left
alone, so a second run does nothing and an interrupted one resumes.

Usage: docker compose exec backend uv run python -m scripts.make_cover_thumbnails
       [--dir /data/covers]
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from app.config import settings
    from app.services.storage import make_missing_thumbnails

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=settings.covers_dir)
    args = parser.parse_args()
    seen, made, failed = make_missing_thumbnails(
        args.dir,
        on_progress=lambda seen, made: logger.info(
            "  %d covers, %d thumbnails made", seen, made
        ),
    )
    logger.info("%d covers, %d thumbnails made, %d failed", seen, made, failed)


if __name__ == "__main__":
    main()
