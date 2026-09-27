"""Move data out of the pre-0.14 per-kind volumes into the single /data one.

Up to 0.13 compose kept app, books, covers and illustrations in four named
volumes; now one volume holds all four as subdirectories under /data (the
paths inside the container are unchanged, so stored file paths stay
valid). The migrate service mounts the old volumes at /legacy/<kind> and
runs this before anything else touches /data.

File by file — copy to a temp name, rename into place, delete the source
— so an interrupted move resumes where it stopped and never needs twice
the space (the two volumes are separate mounts: a plain rename can't
cross them). Only Docker-managed volumes are emptied: a legacy volume
that is really a bind mount onto the user's own directory is left alone,
with instructions, rather than drained into Docker's storage.

Stdlib only, and nothing from app/ — importing the settings would
generate a SECRET_KEY before the old one has moved.
"""

import os
import shutil
import sys
from pathlib import Path

KINDS = ("app", "books", "covers", "illustrations")
LEGACY = Path("/legacy")
DATA = Path("/data")
PROGRESS_EVERY = 2000


def mount_root(path: Path) -> str | None:
    """The source directory backing the mount at ``path`` (mountinfo field
    4), or None when ``path`` isn't a mount point of its own."""
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) > 4 and fields[4] == str(path):
            return fields[3]
    return None


def is_docker_volume(path: Path) -> bool:
    # Named local volumes live at <docker root>/volumes/<name>/_data —
    # also under rootless Docker and Synology's /volume1/@docker.
    root = mount_root(path)
    return root is not None and "/volumes/" in root and root.endswith("/_data")


def move_tree(src: Path, dst: Path) -> tuple[int, int]:
    moved = kept = 0
    for dirpath, _dirnames, filenames in os.walk(src):
        rel = Path(dirpath).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            source = Path(dirpath) / name
            target = target_dir / name
            if target.exists():
                if target.stat().st_size == source.stat().st_size:
                    # Copied before an interruption; finish the move.
                    source.unlink()
                    moved += 1
                else:
                    # Never overwrite: leave both and say so.
                    print(f"  conflict, kept both: {target}", flush=True)
                    kept += 1
                continue
            tmp = target_dir / f".{name}.moving"
            shutil.copy2(source, tmp)
            st = source.stat()
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except OSError:
                pass
            os.replace(tmp, target)
            source.unlink()
            moved += 1
            if moved % PROGRESS_EVERY == 0:
                print(f"  {moved} files moved...", flush=True)
    # Drop the emptied directories, deepest first; the volume root stays.
    for dirpath, _dirnames, _filenames in os.walk(src, topdown=False):
        if Path(dirpath) != src:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    return moved, kept


def main() -> int:
    if not LEGACY.is_dir():
        return 0
    for kind in KINDS:
        src = LEGACY / kind
        if not src.is_dir() or not any(src.iterdir()):
            continue
        dst = DATA / kind
        if not is_docker_volume(src):
            print(
                f"{src} is not a Docker-managed volume (a bind mount?) — "
                f"leaving it untouched. Mount that directory at {dst} "
                "yourself; see the README's Data and Backups section.",
                flush=True,
            )
            continue
        print(f"Moving the old {kind} volume into {dst}...", flush=True)
        moved, kept = move_tree(src, dst)
        print(f"  done: {moved} files moved, {kept} conflicts left", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
