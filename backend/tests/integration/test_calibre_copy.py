"""Copying a linked Calibre library in: the same rows, their files now
BeePub's own, the library an ordinary one."""

import os
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.config import settings
from app.services import calibre
from tests.factories.epub import build_epub

pytestmark = pytest.mark.integration

SCHEMA = """
CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, path TEXT,
  has_cover INTEGER, pubdate TEXT, timestamp TEXT, last_modified TEXT,
  series_index REAL);
CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT,
  name TEXT, uncompressed_size INTEGER);
CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_authors_link (book INTEGER, author INTEGER);
CREATE TABLE comments (book INTEGER, text TEXT);
CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_publishers_link (book INTEGER, publisher INTEGER);
CREATE TABLE identifiers (book INTEGER, type TEXT, val TEXT);
CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_series_link (book INTEGER, series INTEGER);
CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_tags_link (book INTEGER, tag INTEGER);
"""

TITLES = ["鹽田日誌", "候鳥郵局", "半島氣象台"]


def _calibre_library(root: Path) -> Path:
    """A Calibre folder of three EPUBs, as Calibre lays one out."""
    root.mkdir()
    db = sqlite3.connect(root / "metadata.db")
    db.executescript(SCHEMA)
    db.execute("INSERT INTO authors VALUES (1, '岬野千尋')")
    for n, title in enumerate(TITLES, start=1):
        folder = f"Misaki/{title} ({n})"
        (root / folder).mkdir(parents=True)
        data = build_epub(title=title, authors=("岬野千尋",), cover=False)
        (root / folder / f"{title}.epub").write_bytes(data)
        db.execute(
            "INSERT INTO books VALUES (?, ?, ?, 0, NULL, ?, ?, 1.0)",
            (
                n,
                title,
                folder,
                "2026-01-05 08:00:00+00:00",
                "2026-01-05 08:00:00+00:00",
            ),
        )
        db.execute(
            "INSERT INTO data VALUES (?, ?, 'EPUB', ?, ?)", (n, n, title, len(data))
        )
        db.execute("INSERT INTO books_authors_link VALUES (?, 1)", (n,))
    db.commit()
    db.close()
    return root


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "books_dir", str(tmp_path / "books"))
    monkeypatch.setattr(settings, "covers_dir", str(tmp_path / "covers"))
    return tmp_path


async def _linked(admin_client, root: Path) -> tuple[str, list[dict]]:
    """Link the folder and sync it (in this process, not the worker's)."""
    me = (await admin_client.get("/api/auth/me")).json()
    response = await admin_client.post("/api/libraries", json={"name": "Calibre Shelf"})
    assert response.status_code in (200, 201), response.text
    library_id = response.json()["id"]
    from sqlalchemy import update

    from app.database import AsyncSessionLocal
    from app.models.library import Library

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Library)
            .where(Library.id == uuid.UUID(library_id))
            .values(calibre_path=str(root), auto_sync=True)
        )
        await db.commit()
    await calibre.sync_calibre_library(
        str(root), uuid.UUID(library_id), uuid.UUID(me["id"])
    )
    return library_id, await _books(admin_client, library_id)


async def _books(client, library_id: str) -> list[dict]:
    response = await client.get(
        "/api/books", params={"library": library_id, "sort": "display_title"}
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    return [(await client.get(f"/api/books/{b['id']}")).json() for b in items]


async def _digests(book_ids: list[str]) -> dict[str, str | None]:
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.book import Book

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Book.id, Book.partial_md5).where(
                Book.id.in_([uuid.UUID(i) for i in book_ids])
            )
        )
        return {str(i): digest for i, digest in rows.all()}


async def test_copy_keeps_the_rows_and_frees_them(admin_client, storage):
    root = _calibre_library(storage / "calibre")
    library_id, before = await _linked(admin_client, root)
    assert len(before) == 3
    assert all(b["calibre_id"] is not None for b in before)
    first = before[0]
    # An override, and something read: both must outlive the copy.
    response = await admin_client.patch(
        "/api/books/metadata", json={"book_ids": [first["id"]], "publisher": "汐風社"}
    )
    assert response.status_code == 200, response.text
    # A Calibre book is not deleted from a list while Calibre has it.
    response = await admin_client.post(
        "/api/books/delete", json={"book_ids": [first["id"]]}
    )
    assert response.status_code == 409

    digests = await _digests([b["id"] for b in before])
    assert all(digests.values())

    preview = (
        await admin_client.get(f"/api/admin/calibre/libraries/{library_id}/copy")
    ).json()
    assert preview["book_count"] == 3 and preview["unreadable_count"] == 0
    assert preview["bytes_needed"] > 0

    await calibre.copy_calibre_library(uuid.UUID(library_id))
    status = (
        await admin_client.get(f"/api/admin/calibre/libraries/{library_id}/status")
    ).json()
    assert status["sync"]["mode"] == "copy"
    assert status["sync"]["status"] == "completed", status
    assert status["calibre_path"] is None

    after = await _books(admin_client, library_id)
    assert [b["id"] for b in after] == [b["id"] for b in before]
    # The same bytes: KOReader's key for the book has not moved.
    assert await _digests([b["id"] for b in after]) == digests
    for was, now in zip(before, after):
        assert now["calibre_id"] is None
        assert now["display_title"] == was["display_title"]
    assert after[0]["publisher"] == "汐風社"
    copies = sorted(os.listdir(settings.books_dir))
    assert copies == sorted(f"{b['id']}.epub" for b in after)
    library = (await admin_client.get(f"/api/libraries/{library_id}")).json()
    assert library["calibre_path"] is None

    # Calibre's folder can go: the books are read from BeePub's storage.
    shutil.rmtree(root)
    response = await admin_client.get(f"/api/books/{first['id']}/file")
    assert response.status_code == 200
    # And they are BeePub's to delete.
    response = await admin_client.post(
        "/api/books/delete", json={"book_ids": [first["id"]]}
    )
    assert response.status_code == 204, response.text
    assert not os.path.exists(os.path.join(settings.books_dir, f"{first['id']}.epub"))


async def test_copy_stops_before_changing_anything(admin_client, storage, monkeypatch):
    root = _calibre_library(storage / "calibre")
    library_id, before = await _linked(admin_client, root)
    lost = next(b for b in before if b["display_title"] == "候鳥郵局")
    os.remove(next(root.glob("**/候鳥郵局.epub")))

    # A file that cannot be read: named, and nothing changed.
    await calibre.copy_calibre_library(uuid.UUID(library_id))
    status = (
        await admin_client.get(f"/api/admin/calibre/libraries/{library_id}/status")
    ).json()
    assert status["sync"]["status"] == "failed"
    assert status["sync"]["reason"] == "unreadable"
    assert status["sync"]["unreadable"] == ["候鳥郵局"]
    assert status["calibre_path"] == str(root)
    assert all(
        b["calibre_id"] is not None for b in await _books(admin_client, library_id)
    )

    # No room: the same.
    real = shutil.disk_usage
    monkeypatch.setattr(
        calibre.shutil,
        "disk_usage",
        lambda path: real(path)._replace(free=1024),
    )
    await calibre.copy_calibre_library(uuid.UUID(library_id), skip_unreadable=True)
    status = (
        await admin_client.get(f"/api/admin/calibre/libraries/{library_id}/status")
    ).json()
    assert status["sync"]["reason"] == "space"
    assert status["sync"]["bytes_free"] == 1024
    assert status["calibre_path"] == str(root)
    monkeypatch.undo()
    monkeypatch.setattr(settings, "books_dir", str(storage / "books"))
    monkeypatch.setattr(settings, "covers_dir", str(storage / "covers"))

    # Without the lost book: the other two come in, that one goes.
    await calibre.copy_calibre_library(uuid.UUID(library_id), skip_unreadable=True)
    status = (
        await admin_client.get(f"/api/admin/calibre/libraries/{library_id}/status")
    ).json()
    assert status["sync"]["status"] == "completed", status
    after = await _books(admin_client, library_id)
    assert sorted(b["display_title"] for b in after) == ["半島氣象台", "鹽田日誌"]
    assert (await admin_client.get(f"/api/books/{lost['id']}")).status_code == 404


async def test_a_sync_stays_out_of_a_copy(admin_client, storage):
    root = _calibre_library(storage / "calibre")
    library_id, before = await _linked(admin_client, root)
    from redis.asyncio import Redis

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.set(calibre._copy_lock_key(uuid.UUID(library_id)), "1", ex=60)
        response = await admin_client.post(
            f"/api/admin/calibre/libraries/{library_id}/sync"
        )
        assert response.status_code == 409
        response = await admin_client.post(
            f"/api/admin/calibre/libraries/{library_id}/copy", json={}
        )
        assert response.status_code == 409
        # A book gone from Calibre is not removed by a sync that must wait.
        os.remove(next(root.glob("**/鹽田日誌.epub")))
        sqlite3.connect(root / "metadata.db").execute(
            "DELETE FROM data WHERE book = 1"
        ).connection.commit()
        me = (await admin_client.get("/api/auth/me")).json()
        await calibre.sync_calibre_library(
            str(root), uuid.UUID(library_id), uuid.UUID(me["id"])
        )
        assert len(await _books(admin_client, library_id)) == 3
    finally:
        await redis.delete(calibre._copy_lock_key(uuid.UUID(library_id)))
        await redis.aclose()
