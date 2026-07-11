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

    # …and the percentage shows up in BeePub's own reading progress (0-100),
    # with the kosync marker the web reader uses to offer the jump.
    progress = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert progress["percentage"] == pytest.approx(42.69)
    assert progress["kosync"]["percentage"] == pytest.approx(42.69)
    assert progress["kosync"]["device"] == "kobo"
    assert progress["kosync"]["synced_at"]
    # DocFragment[7] = 1-based spine item → 0-based section hint 6, and the
    # raw xpointer rides along for the reader's paragraph-level resolution.
    assert progress["kosync"]["section_index"] == 6
    assert progress["kosync"]["xpointer"] == payload["progress"]


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


async def test_digest_job_fills_missing_digests(admin_client):
    from sqlalchemy import update

    from app.database import engine
    from app.models.book import Book
    from app.tasks.digests import _run_book_digest

    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    original = await _document_digest(admin_client, book["id"])

    # Simulate a book that predates kosync support.
    async with engine.begin() as conn:
        await conn.execute(update(Book).values(partial_md5=None))

    await _run_book_digest(book["id"])
    assert await _document_digest(admin_client, book["id"]) == original


async def test_digest_job_marks_unreadable_files(admin_client):
    from sqlalchemy import update

    from app.database import engine
    from app.models.book import Book
    from app.tasks.digests import _run_book_digest

    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    async with engine.begin() as conn:
        await conn.execute(
            update(Book).values(partial_md5=None, file_path="/nonexistent.epub")
        )

    # "" keeps the book out of the missing count instead of retrying forever.
    await _run_book_digest(book["id"])
    assert await _document_digest(admin_client, book["id"]) == ""


async def test_auto_kick_starts_the_bulk_job(admin_client):
    from sqlalchemy import update

    from app.database import engine
    from app.models.book import Book
    from app.services.job_queue import get_generation
    from app.tasks.digests import _auto_kick

    library_id = await create_library(admin_client)
    await upload_epub(admin_client, library_id)

    # Nothing missing → no run started.
    assert await _auto_kick() is False

    async with engine.begin() as conn:
        await conn.execute(update(Book).values(partial_md5=None))
    generation_before = await get_generation("digest")
    assert await _auto_kick() is True
    assert await get_generation("digest") == generation_before + 1


async def test_digest_job_retro_bridges_preexisting_records(admin_client):
    """Progress that arrived before the book had a digest gets applied."""
    from sqlalchemy import update

    from app.database import engine
    from app.models.book import Book
    from app.tasks.digests import _run_book_digest

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

    await _run_book_digest(book["id"])
    after = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert after["percentage"] == pytest.approx(33.0)
    assert after["kosync"]["percentage"] == pytest.approx(33.0)


async def test_bridge_sets_reading_status(admin_client):
    """A kosync push makes the book show up as currently reading."""
    from sqlalchemy import select

    from app.database import engine
    from app.models.reading import UserBookInteraction

    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": document, "progress": "xp", "percentage": 0.2},
        headers=_headers(),
    )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(
                    UserBookInteraction.reading_status,
                    UserBookInteraction.started_at,
                )
            )
        ).one()
    assert row.reading_status == "currently_reading"
    assert row.started_at is not None


async def test_bridge_never_demotes_reading_status(admin_client):
    from sqlalchemy import select, update

    from app.database import engine
    from app.models.reading import UserBookInteraction

    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": document, "progress": "xp", "percentage": 0.5},
        headers=_headers(),
    )
    async with engine.begin() as conn:
        await conn.execute(update(UserBookInteraction).values(reading_status="read"))

    # A re-read on the e-reader must not flip a finished book back.
    await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": document, "progress": "xp2", "percentage": 0.6},
        headers=_headers(),
    )
    async with engine.connect() as conn:
        status_value = (
            await conn.execute(select(UserBookInteraction.reading_status))
        ).scalar_one()
    assert status_value == "read"


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


async def test_web_save_clears_kosync_marker(admin_client):
    """The marker means "device position is newer than the stored CFI" —
    a web save rebuilds the progress dict, so the marker must not survive."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": document, "progress": "xp", "percentage": 0.3},
        headers=_headers(),
    )
    progress = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert progress["kosync"]["percentage"] == pytest.approx(30.0)

    saved = await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={"cfi": "epubcfi(/6/10!/4/2/1:0)", "percentage": 31.0},
    )
    assert saved.status_code == 200
    progress = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert progress["kosync"] is None
    assert progress["percentage"] == pytest.approx(31.0)


async def test_get_serves_web_position_when_web_is_newer(admin_client):
    """Chapter-level web→KOReader: after the user reads on the web (which
    clears the kosync marker), GET synthesizes a DocFragment position as
    device "BeePub Web" instead of replaying the stale device record."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    await admin_client.put(
        "/kosync/syncs/progress",
        json={
            "document": document,
            "progress": "/body/DocFragment[2]/body/p[1]/text().0",
            "percentage": 0.2,
            "device": "kobo",
        },
        headers=_headers(),
    )

    # The user then reads further on the web.
    saved = await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={
            "cfi": "epubcfi(/6/10!/4/2/1:0)",
            "percentage": 55.5,
            "section_index": 4,
        },
    )
    assert saved.status_code == 200

    fetched = (
        await admin_client.get(f"/kosync/syncs/progress/{document}", headers=_headers())
    ).json()
    assert fetched["device"] == "BeePub Web"
    assert fetched["progress"] == "/body/DocFragment[5]/body"
    assert fetched["percentage"] == pytest.approx(0.555)


async def test_get_serves_web_xpointer_when_reader_computed_one(admin_client):
    """Paragraph-level web→device: when the reader shipped an xpointer with
    its save, GET serves it verbatim instead of the chapter-start synthesis."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    xpointer = "/body/DocFragment[5]/body/div/p[7]/text().42"
    saved = await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={
            "cfi": "epubcfi(/6/10!/4/2/14/1:42)",
            "percentage": 55.5,
            "section_index": 4,
            "xpointer": xpointer,
        },
    )
    assert saved.status_code == 200

    fetched = (
        await admin_client.get(f"/kosync/syncs/progress/{document}", headers=_headers())
    ).json()
    assert fetched["device"] == "BeePub Web"
    assert fetched["progress"] == xpointer
    assert fetched["percentage"] == pytest.approx(0.555)

    # A later save without an xpointer (e.g. computation failed) must not
    # replay the stale one — the dict rebuild drops it, degrading to the
    # chapter start.
    saved = await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={
            "cfi": "epubcfi(/6/12!/4/2/1:0)",
            "percentage": 60.0,
            "section_index": 5,
        },
    )
    assert saved.status_code == 200
    fetched = (
        await admin_client.get(f"/kosync/syncs/progress/{document}", headers=_headers())
    ).json()
    assert fetched["progress"] == "/body/DocFragment[6]/body"


async def test_get_serves_device_record_when_device_is_newer(admin_client):
    """A device push after the web save restores the marker — GET must
    return the device record verbatim so KOReader↔KOReader stays exact."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={
            "cfi": "epubcfi(/6/4!/4/2/1:0)",
            "percentage": 10.0,
            "section_index": 1,
        },
    )
    await admin_client.put(
        "/kosync/syncs/progress",
        json={
            "document": document,
            "progress": "/body/DocFragment[9]/body/p[4]/text().12",
            "percentage": 0.9,
            "device": "kobo",
        },
        headers=_headers(),
    )

    fetched = (
        await admin_client.get(f"/kosync/syncs/progress/{document}", headers=_headers())
    ).json()
    assert fetched["device"] == "kobo"
    assert fetched["progress"] == "/body/DocFragment[9]/body/p[4]/text().12"
    assert fetched["percentage"] == pytest.approx(0.9)


async def test_get_serves_web_position_without_device_record(admin_client):
    """A book only ever read on the web still syncs down to a first-time
    KOReader pull."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={
            "cfi": "epubcfi(/6/8!/4/2/1:0)",
            "percentage": 40.0,
            "section_index": 3,
        },
    )

    fetched = (
        await admin_client.get(f"/kosync/syncs/progress/{document}", headers=_headers())
    ).json()
    assert fetched["device"] == "BeePub Web"
    assert fetched["progress"] == "/body/DocFragment[4]/body"
    assert fetched["percentage"] == pytest.approx(0.4)


async def test_cfi_save_without_percentage_keeps_bridged_value(admin_client):
    """The reader saves percentage=null while locations are still generating;
    the CFI must be stored without zeroing the kosync-bridged percentage."""
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    document = await _document_digest(admin_client, book["id"])

    await admin_client.put(
        "/kosync/syncs/progress",
        json={"document": document, "progress": "xp", "percentage": 0.23},
        headers=_headers(),
    )

    saved = await admin_client.put(
        f"/api/books/{book['id']}/progress",
        json={"cfi": "epubcfi(/6/4!/4/2/1:0)", "percentage": None},
    )
    assert saved.status_code == 200
    progress = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert progress["cfi"] == "epubcfi(/6/4!/4/2/1:0)"
    assert progress["percentage"] == pytest.approx(23.0)
    assert progress["kosync"] is None
