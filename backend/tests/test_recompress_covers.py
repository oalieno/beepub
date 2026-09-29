"""The one-off cover re-encode (scripts/recompress_covers.py)."""

import importlib.util
import io
import os
from pathlib import Path

from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "recompress_covers",
    Path(__file__).resolve().parents[1] / "scripts" / "recompress_covers.py",
)
recompress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recompress)


def _noisy_jpeg(size: tuple[int, int], quality: int = 100) -> bytes:
    # Noise keeps the JPEG large, like a real full-size scan.
    img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def test_rewrites_big_covers_in_place_and_keeps_mtime(tmp_path):
    big = tmp_path / "big.jpg"
    big.write_bytes(_noisy_jpeg((1600, 2400)))
    os.utime(big, (1_000_000_000, 1_000_000_000))
    before = big.stat().st_size

    seen, rewritten, failed, saved = recompress.run(tmp_path)

    assert (seen, rewritten, failed) == (1, 1, 0)
    assert big.stat().st_size < before
    assert saved == before - big.stat().st_size
    assert big.stat().st_mtime == 1_000_000_000
    with Image.open(big) as img:
        assert img.size == (800, 1200)
    assert [p.name for p in tmp_path.iterdir()] == ["big.jpg"]


def test_small_covers_are_left_alone(tmp_path):
    small = tmp_path / "small.jpg"
    data = _noisy_jpeg((400, 600), quality=85)
    small.write_bytes(data)

    assert recompress.run(tmp_path)[1] == 0
    assert small.read_bytes() == data


def test_second_run_is_a_no_op(tmp_path):
    (tmp_path / "a.jpg").write_bytes(_noisy_jpeg((1600, 2400)))
    assert recompress.run(tmp_path)[1] == 1
    after = (tmp_path / "a.jpg").read_bytes()

    assert recompress.run(tmp_path)[1] == 0
    assert (tmp_path / "a.jpg").read_bytes() == after


def test_dry_run_writes_nothing(tmp_path):
    data = _noisy_jpeg((1600, 2400))
    (tmp_path / "a.jpg").write_bytes(data)

    seen, rewritten, _failed, saved = recompress.run(tmp_path, dry_run=True)

    assert (seen, rewritten) == (1, 1) and saved > 0
    assert (tmp_path / "a.jpg").read_bytes() == data


def test_unreadable_files_and_leftovers(tmp_path):
    (tmp_path / "broken.jpg").write_bytes(b"x" * (300 * 1024))
    (tmp_path / "a.jpg.recompress").write_bytes(b"half written")
    (tmp_path / "a.jpg.tmp-1234").write_bytes(b"an upload in flight")

    seen, rewritten, failed, _saved = recompress.run(tmp_path)

    assert (seen, rewritten, failed) == (1, 0, 1)
    assert (tmp_path / "broken.jpg").exists()
    assert not (tmp_path / "a.jpg.recompress").exists()
    assert (tmp_path / "a.jpg.tmp-1234").exists()
