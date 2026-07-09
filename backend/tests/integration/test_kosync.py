"""KOReader progress sync — the kosync-compatible endpoints."""

import hashlib
import time

import pytest

from tests.integration.conftest import ADMIN_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


def _headers(credentials=ADMIN_CREDENTIALS) -> dict[str, str]:
    # The stock client sends md5(password) as the key.
    return {
        "x-auth-user": credentials["username"],
        "x-auth-key": hashlib.md5(credentials["password"].encode()).hexdigest(),
    }


async def _document_digest(client, book_id: str) -> str:
    """The digest KOReader would compute for the book's file."""
    from sqlalchemy import select

    from app.database import engine
    from app.models.book import Book

    async with engine.connect() as conn:
        result = await conn.execute(select(Book.partial_md5).where(Book.id == book_id))
        return result.scalar_one()


async def test_auth_roundtrip(admin_client):
    response = await admin_client.get("/kosync/users/auth", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"authorized": "OK"}


async def test_auth_rejects_bad_key(admin_client):
    headers = _headers() | {"x-auth-key": hashlib.md5(b"wrong").hexdigest()}
    assert (
        await admin_client.get("/kosync/users/auth", headers=headers)
    ).status_code == 401
    assert (await admin_client.get("/kosync/users/auth")).status_code == 401


async def test_register_is_disabled(admin_client):
    response = await admin_client.post(
        "/kosync/users/create", json={"username": "x", "password": "y"}
    )
    assert response.status_code == 403
    assert "message" in response.json()


async def test_progress_roundtrip_and_bridge(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id, title="Kobo Book")
    document = await _document_digest(admin_client, book["id"])
    assert document  # upload computed the digest

    payload = {
        "document": document,
        "progress": "/body/DocFragment[7]/body/div/p[3]/text().0",
        "percentage": 0.4269,
        "device": "kobo",
        "device_id": "ABC123",
    }
    response = await admin_client.put(
        "/kosync/syncs/progress", json=payload, headers=_headers()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document"] == document
    assert body["timestamp"] == pytest.approx(time.time(), abs=30)

    # KOReader on another device pulls the exact same record back.
    response = await admin_client.get(
        f"/kosync/syncs/progress/{document}", headers=_headers()
    )
    fetched = response.json()
    assert fetched["progress"] == payload["progress"]
    assert fetched["percentage"] == payload["percentage"]
    assert fetched["device"] == "kobo"

    # …and the percentage shows up in BeePub's own reading progress (0-100).
    progress = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert progress["percentage"] == pytest.approx(42.69)


async def test_unknown_document_is_stored_but_not_bridged(admin_client):
    document = hashlib.md5(b"sideloaded file").hexdigest()
    response = await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": document, "progress": "10", "percentage": 0.5},
        headers=_headers(),
    )
    assert response.status_code == 200

    fetched = (
        await admin_client.get(f"/kosync/syncs/progress/{document}", headers=_headers())
    ).json()
    assert fetched["percentage"] == 0.5


async def test_no_progress_yet(admin_client):
    document = hashlib.md5(b"never seen").hexdigest()
    response = await admin_client.get(
        f"/kosync/syncs/progress/{document}", headers=_headers()
    )
    # The stock client checks body.percentage to decide "no progress".
    assert response.status_code == 200
    assert "percentage" not in response.json()


async def test_backfill_fills_missing_digests(admin_client):
    from sqlalchemy import update

    from app.database import engine
    from app.models.book import Book
    from app.tasks.digests import _run_backfill

    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    original = await _document_digest(admin_client, book["id"])

    # Simulate a book that predates kosync support.
    async with engine.begin() as conn:
        await conn.execute(update(Book).values(partial_md5=None))

    assert await _run_backfill() == 1
    assert await _document_digest(admin_client, book["id"]) == original


async def test_backfill_retro_bridges_preexisting_records(admin_client):
    """Progress that arrived before the book had a digest gets applied."""
    from sqlalchemy import update

    from app.database import engine
    from app.models.book import Book
    from app.tasks.digests import _run_backfill

    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    digest = await _document_digest(admin_client, book["id"])

    # Pre-upgrade state: the book has no digest yet…
    async with engine.begin() as conn:
        await conn.execute(update(Book).values(partial_md5=None))

    # …so this push is stored but cannot bridge.
    await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": digest, "progress": "xp", "percentage": 0.33},
        headers=_headers(),
    )
    before = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert before == {} or before.get("percentage") is None

    assert await _run_backfill() == 1
    after = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert after["percentage"] == pytest.approx(33.0)


async def test_bridge_preserves_existing_reader_state(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    # Web reader saved a full progress record…
    saved = await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={"cfi": "epubcfi(/6/8!/4/2/1:0)", "percentage": 10.0},
    )
    assert saved.status_code == 200

    # …then the e-reader pushes; cfi must survive, percentage must update.
    await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": document, "progress": "xp", "percentage": 0.9},
        headers=_headers(),
    )
    progress = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert progress["cfi"] == "epubcfi(/6/8!/4/2/1:0)"
    assert progress["percentage"] == pytest.approx(90.0)
