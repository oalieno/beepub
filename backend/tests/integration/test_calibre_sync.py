"""Syncing a linked Calibre library: what one bad book, and a Calibre
that suddenly lists nothing, may and may not do to the rest."""

import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.services import calibre
from tests.integration.test_calibre_copy import (
    TITLES,
    _books,
    _calibre_library,
    _linked,
    storage,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.integration


async def _sync(admin_client, root: Path, library_id: str) -> dict:
    me = (await admin_client.get("/api/auth/me")).json()
    await calibre.sync_calibre_library(
        str(root), uuid.UUID(library_id), uuid.UUID(me["id"])
    )
    status = await calibre.get_sync_status(uuid.UUID(library_id))
    assert status is not None
    return status


def _titles(books: list[dict]) -> list[str]:
    return sorted(b["display_title"] for b in books)


async def test_a_book_the_database_refuses_does_not_cost_the_others(
    admin_client,
    tmp_path,
    storage,  # noqa: F811
):
    root = _calibre_library(tmp_path / "calibre")
    # Postgres will not store a NUL in text: this row cannot be written.
    db = sqlite3.connect(root / "metadata.db")
    db.execute("UPDATE books SET title = ? WHERE id = 2", ("候鳥\x00郵局",))
    db.commit()
    db.close()

    library_id, books = await _linked(admin_client, root)

    assert _titles(books) == sorted([TITLES[0], TITLES[2]])
    status = await calibre.get_sync_status(uuid.UUID(library_id))
    assert status["status"] == "completed"
    assert (status["added"], status["skipped"]) == (2, 1)


async def test_a_book_gone_from_calibre_is_removed(admin_client, tmp_path, storage):  # noqa: F811
    root = _calibre_library(tmp_path / "calibre")
    library_id, books = await _linked(admin_client, root)
    assert _titles(books) == sorted(TITLES)

    # As Calibre does it: the row and the book's folder both go.
    db = sqlite3.connect(root / "metadata.db")
    db.execute("DELETE FROM data WHERE book = 3")
    db.execute("DELETE FROM books WHERE id = 3")
    db.commit()
    db.close()
    shutil.rmtree(root / f"Misaki/{TITLES[2]} (3)")

    status = await _sync(admin_client, root, library_id)
    assert status["removed"] == 1
    assert _titles(await _books(admin_client, library_id)) == sorted(TITLES[:2])


async def test_a_book_missing_from_the_list_but_still_on_disk_is_kept(
    admin_client,
    tmp_path,
    storage,  # noqa: F811
):
    root = _calibre_library(tmp_path / "calibre")
    library_id, books = await _linked(admin_client, root)

    # The list loses a book the folder still has: they disagree.
    db = sqlite3.connect(root / "metadata.db")
    db.execute("DELETE FROM data WHERE book = 3")
    db.execute("DELETE FROM books WHERE id = 3")
    db.commit()
    db.close()

    status = await _sync(admin_client, root, library_id)
    assert status["removed"] == 0
    assert any("still on disk" in e for e in status["errors"])
    assert _titles(await _books(admin_client, library_id)) == sorted(TITLES)


async def test_a_calibre_that_lists_nothing_removes_nothing(
    admin_client,
    tmp_path,
    storage,  # noqa: F811
):
    root = _calibre_library(tmp_path / "calibre")
    library_id, books = await _linked(admin_client, root)
    marked = books[0]["id"]
    response = await admin_client.put(
        f"/api/books/{marked}/notes", json={"notes": "kept through the outage"}
    )
    assert response.status_code == 200, response.text

    # An unmounted folder, or a metadata.db caught half-written.
    db = sqlite3.connect(root / "metadata.db")
    db.execute("DELETE FROM data")
    db.commit()
    db.close()

    status = await _sync(admin_client, root, library_id)
    assert status["removed"] == 0
    assert any("lists no books" in e for e in status["errors"])
    assert _titles(await _books(admin_client, library_id)) == sorted(TITLES)
    interaction = (await admin_client.get(f"/api/books/{marked}/interaction")).json()
    assert interaction["notes"] == "kept through the outage"
