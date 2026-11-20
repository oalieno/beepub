"""The walk that gives stored covers their thumbnails, and who starts it."""

import io
import os
from types import SimpleNamespace

from PIL import Image

from app.services.storage import cover_thumbnail_path, make_missing_thumbnails
from app.tasks import covers


def _cover(path) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (800, 1200), (40, 90, 160)).save(buf, "JPEG")
    path.write_bytes(buf.getvalue())
    return str(path)


def test_makes_what_is_missing_and_then_nothing(tmp_path):
    a = _cover(tmp_path / "a.jpg")
    b = _cover(tmp_path / "b.jpg")
    (tmp_path / "notes.txt").write_text("not a cover")

    assert make_missing_thumbnails(str(tmp_path)) == (2, 2, 0)
    for cover in (a, b):
        with Image.open(cover_thumbnail_path(cover)) as img:
            assert img.format == "WEBP"
    # Every thumbnail is current: a second walk writes nothing.
    assert make_missing_thumbnails(str(tmp_path)) == (2, 0, 0)


def test_a_thumbnail_older_than_its_cover_is_made_again(tmp_path):
    cover = _cover(tmp_path / "a.jpg")
    make_missing_thumbnails(str(tmp_path))
    thumbnail = cover_thumbnail_path(cover)
    os.utime(thumbnail, ns=(1_000_000_000, 1_000_000_000))

    assert make_missing_thumbnails(str(tmp_path)) == (1, 1, 0)
    assert os.stat(thumbnail).st_mtime_ns >= os.stat(cover).st_mtime_ns


def test_a_cover_that_is_not_a_picture_is_counted_and_left(tmp_path):
    (tmp_path / "broken.jpg").write_bytes(b"not a jpeg")

    assert make_missing_thumbnails(str(tmp_path)) == (1, 0, 1)
    assert not os.path.exists(cover_thumbnail_path(str(tmp_path / "broken.jpg")))
    # No temp file left behind.
    thumbs = tmp_path / "thumb"
    assert not thumbs.exists() or not any(thumbs.iterdir())


def test_a_missing_directory_is_no_covers(tmp_path):
    assert make_missing_thumbnails(str(tmp_path / "nowhere")) == (0, 0, 0)


def test_only_the_bulk_worker_queues_the_walk(monkeypatch):
    queued = []
    monkeypatch.setattr(
        covers.make_missing_thumbnails,
        "apply_async",
        lambda **kwargs: queued.append(kwargs),
    )

    covers._start_on_bulk_worker(sender=SimpleNamespace(hostname="default@host"))
    assert queued == []
    covers._start_on_bulk_worker(sender=SimpleNamespace(hostname="bulk@host"))
    assert queued == [{"queue": "bulk"}]
