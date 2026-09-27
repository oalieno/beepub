"""The pre-0.14 volume merge (scripts/merge_data_volumes.py)."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "merge_data_volumes",
    Path(__file__).resolve().parents[1] / "scripts" / "merge_data_volumes.py",
)
merge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge)


@pytest.fixture
def layout(tmp_path, monkeypatch):
    legacy, data = tmp_path / "legacy", tmp_path / "data"
    for kind in merge.KINDS:
        (legacy / kind).mkdir(parents=True)
    data.mkdir()
    monkeypatch.setattr(merge, "LEGACY", legacy)
    monkeypatch.setattr(merge, "DATA", data)
    monkeypatch.setattr(merge, "is_docker_volume", lambda _path: True)
    return legacy, data


def test_moves_every_kind_and_empties_the_old_volumes(layout):
    legacy, data = layout
    (legacy / "app" / "secret_key").write_text("s3cret")
    (legacy / "covers" / "ab").mkdir()
    (legacy / "covers" / "ab" / "1.jpg").write_bytes(b"jpeg")
    (legacy / "books" / "1.epub").write_bytes(b"epub")

    assert merge.main() == 0

    assert (data / "app" / "secret_key").read_text() == "s3cret"
    assert (data / "covers" / "ab" / "1.jpg").read_bytes() == b"jpeg"
    assert (data / "books" / "1.epub").read_bytes() == b"epub"
    # Emptied, subdirectories included; the volume roots stay.
    for kind in merge.KINDS:
        assert list((legacy / kind).iterdir()) == []


def test_resumes_after_an_interruption(layout):
    legacy, data = layout
    # A previous run copied this file but died before deleting the source.
    (legacy / "books" / "1.epub").write_bytes(b"epub")
    (data / "books").mkdir()
    (data / "books" / "1.epub").write_bytes(b"epub")
    (legacy / "books" / "2.epub").write_bytes(b"two")

    merge.main()

    assert sorted(p.name for p in (data / "books").iterdir()) == [
        "1.epub",
        "2.epub",
    ]
    assert list((legacy / "books").iterdir()) == []


def test_never_overwrites_a_different_file(layout):
    legacy, data = layout
    (legacy / "app" / "secret_key").write_text("old")
    (data / "app").mkdir()
    (data / "app" / "secret_key").write_text("different")

    merge.main()

    assert (data / "app" / "secret_key").read_text() == "different"
    assert (legacy / "app" / "secret_key").read_text() == "old"


def test_leaves_a_bind_mounted_legacy_volume_alone(layout, monkeypatch):
    legacy, data = layout
    (legacy / "books" / "1.epub").write_bytes(b"epub")
    monkeypatch.setattr(merge, "is_docker_volume", lambda _path: False)

    merge.main()

    assert (legacy / "books" / "1.epub").exists()
    assert not (data / "books").exists()


def test_fresh_install_is_a_no_op(layout):
    _legacy, data = layout
    assert merge.main() == 0
    assert list(data.iterdir()) == []


@pytest.mark.parametrize(
    ("root", "managed"),
    [
        ("/var/lib/docker/volumes/beepub_books_data/_data", True),
        ("/volume1/@docker/volumes/beepub_books_data/_data", True),
        ("/home/me/.local/share/docker/volumes/x/_data", True),
        ("/srv/books", False),
    ],
)
def test_docker_volume_detection(monkeypatch, root, managed):
    monkeypatch.setattr(merge, "mount_root", lambda _path: root)
    assert merge.is_docker_volume(Path("/legacy/books")) is managed
