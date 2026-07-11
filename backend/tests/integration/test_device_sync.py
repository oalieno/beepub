"""Device-sync endpoints: digest lookup and reading-state merge."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.conftest import ADMIN_CREDENTIALS, USER_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


def _stamp(offset_seconds: float = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat()


def _sync_highlight(**overrides) -> dict:
    now = _stamp()
    payload = {
        "id": str(uuid.uuid4()),
        "cfi_range": "epubcfi(/6/4!/4/2/2:0,/4/2/4:5)",
        "text": "synced text",
        "color": "yellow",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    payload.update(overrides)
    return payload


def _sync_progress(**overrides) -> dict:
    payload = {
        "cfi": "epubcfi(/6/8!/4/2/2:0)",
        "percentage": 42.5,
        "section_index": 3,
        "last_read_at": _stamp(),
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def book_id(admin_client) -> str:
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    return book["id"]


async def _document_digest(client, book_id: str) -> str:
    """The digest the device computes for the book's file (partial md5)."""
    from sqlalchemy import select

    from app.database import engine
    from app.models.book import Book

    async with engine.connect() as conn:
        result = await conn.execute(select(Book.partial_md5).where(Book.id == book_id))
        return result.scalar_one()


async def _user_id(admin_client, username: str) -> str:
    users = (await admin_client.get("/api/admin/users")).json()
    return next(u["id"] for u in users if u["username"] == username)


async def test_by_digest_matches_accessible_book(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id, title="Linked Book")
    digest = await _document_digest(admin_client, book["id"])

    response = await admin_client.post(
        "/api/books/by-digest",
        json={"digests": [digest, "0" * 32]},
    )
    assert response.status_code == 200
    matches = response.json()["matches"]
    # Known digest resolves; the unknown one is simply absent.
    assert set(matches) == {digest}
    assert matches[digest]["id"] == book["id"]
    assert matches[digest]["title"] == "Linked Book"


async def test_by_digest_empty_request(admin_client):
    response = await admin_client.post("/api/books/by-digest", json={"digests": []})
    assert response.status_code == 200
    assert response.json() == {"matches": {}}


async def test_by_digest_respects_library_exclusion(admin_client, user_client):
    lib = await create_library(admin_client, "Hidden Digest Lib")
    book = await upload_epub(admin_client, lib, title="Hidden Book")
    digest = await _document_digest(admin_client, book["id"])

    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    response = await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": [lib]},
    )
    assert response.status_code == 200, response.text

    matches = (
        await user_client.post("/api/books/by-digest", json={"digests": [digest]})
    ).json()["matches"]
    assert matches == {}

    # Lifting the exclusion restores the match.
    await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": []},
    )
    matches = (
        await user_client.post("/api/books/by-digest", json={"digests": [digest]})
    ).json()["matches"]
    assert matches[digest]["id"] == book["id"]


async def test_by_digest_validates_shape(admin_client):
    # Wrong digest length → 422.
    response = await admin_client.post(
        "/api/books/by-digest", json={"digests": ["abc"]}
    )
    assert response.status_code == 422
    # Oversized batch → 422.
    response = await admin_client.post(
        "/api/books/by-digest", json={"digests": ["a" * 32] * 501}
    )
    assert response.status_code == 422


async def test_by_digest_requires_auth(client):
    response = await client.post(
        "/api/books/by-digest", json={"digests": ["a" * 32]}
    )
    assert response.status_code == 401


# --- POST /api/books/{book_id}/sync ---


async def test_sync_empty_request_returns_current_state(admin_client, book_id):
    response = await admin_client.post(f"/api/books/{book_id}/sync", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["progress"] is None
    assert body["highlights"] == []


async def test_sync_progress_client_wins_when_server_empty(admin_client, book_id):
    stamp = _stamp()
    progress = _sync_progress(last_read_at=stamp, xpointer="/body/DocFragment[4]/body")
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"progress": progress}
    )
    assert response.status_code == 200
    stored = response.json()["progress"]
    assert stored["cfi"] == progress["cfi"]
    assert stored["percentage"] == 42.5
    # The client's stamp is preserved verbatim — server-now would fabricate
    # freshness and misorder the next comparison.
    assert stored["last_read_at"] == stamp
    assert stored["xpointer"] == "/body/DocFragment[4]/body"

    fetched = (await admin_client.get(f"/api/books/{book_id}/progress")).json()
    assert fetched["cfi"] == progress["cfi"]


async def test_sync_progress_server_newer_wins(admin_client, book_id):
    web = {"cfi": "epubcfi(/6/10!/4/2:0)", "percentage": 80.0}
    assert (
        await admin_client.put(f"/api/books/{book_id}/progress", json=web)
    ).status_code == 200

    response = await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(last_read_at=_stamp(-3600))},
    )
    stored = response.json()["progress"]
    assert stored["cfi"] == web["cfi"]
    assert stored["percentage"] == 80.0


async def test_sync_progress_tie_keeps_server(admin_client, book_id):
    stamp = _stamp()
    first = _sync_progress(cfi="epubcfi(/6/2!/4:0)", last_read_at=stamp)
    await admin_client.post(f"/api/books/{book_id}/sync", json={"progress": first})

    second = _sync_progress(cfi="epubcfi(/6/6!/4:0)", last_read_at=stamp)
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"progress": second}
    )
    assert response.json()["progress"]["cfi"] == first["cfi"]


async def test_sync_progress_null_percentage_keeps_previous(admin_client, book_id):
    await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(percentage=33.0)},
    )
    response = await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(percentage=None, last_read_at=_stamp(60))},
    )
    assert response.json()["progress"]["percentage"] == 33.0


async def test_sync_progress_kosync_marker_ordering(admin_client, book_id):
    # A device push through kosync stamps the marker into reading_progress.
    document = await _document_digest(admin_client, book_id)
    kosync_headers = {
        "x-auth-user": ADMIN_CREDENTIALS["username"],
        "x-auth-key": hashlib.md5(
            ADMIN_CREDENTIALS["password"].encode()
        ).hexdigest(),
    }
    push = await admin_client.put(
        "/kosync/syncs/progress",
        headers=kosync_headers,
        json={
            "document": document,
            "progress": "/body/DocFragment[6]/body/p[3]",
            "percentage": 0.5,
            "device": "Kobo",
        },
    )
    assert push.status_code == 200

    # Server wins → the response carries the marker out to the device.
    response = await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(last_read_at=_stamp(-3600))},
    )
    assert response.json()["progress"]["kosync"]["device"] == "Kobo"

    # Client wins → the rebuild drops the marker ("the app moved last").
    response = await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(last_read_at=_stamp(60))},
    )
    assert "kosync" not in response.json()["progress"]


async def test_sync_never_records_reading_activity(admin_client, book_id):
    before = (await admin_client.get("/api/books/reading-activity")).json()
    # Two syncs 30s apart — the interactive PUT would credit this gap.
    await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(last_read_at=_stamp(-30))},
    )
    await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(last_read_at=_stamp())},
    )
    after = (await admin_client.get("/api/books/reading-activity")).json()
    assert after == before


async def test_sync_rejects_naive_timestamps(admin_client, book_id):
    naive = datetime.now().isoformat()  # noqa: DTZ005 — deliberately naive
    response = await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"progress": _sync_progress(last_read_at=naive)},
    )
    assert response.status_code == 422
    response = await admin_client.post(
        f"/api/books/{book_id}/sync",
        json={"highlights": [_sync_highlight(updated_at=naive)]},
    )
    assert response.status_code == 422


async def test_sync_highlight_insert_trusts_client_stamps(admin_client, book_id):
    created = _stamp(-86400)
    updated = _stamp(-3600)
    hl = _sync_highlight(created_at=created, updated_at=updated, note="from device")
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [hl]}
    )
    [stored] = response.json()["highlights"]
    assert stored["id"] == hl["id"]
    assert stored["note"] == "from device"
    assert datetime.fromisoformat(stored["created_at"]) == datetime.fromisoformat(
        created
    )
    assert datetime.fromisoformat(stored["updated_at"]) == datetime.fromisoformat(
        updated
    )

    # Visible through the normal listing too.
    listing = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    assert [h["id"] for h in listing] == [hl["id"]]


async def test_sync_highlight_lww_both_directions(admin_client, book_id):
    hl = _sync_highlight(color="yellow")
    await admin_client.post(f"/api/books/{book_id}/sync", json={"highlights": [hl]})

    # Older client copy loses.
    stale = {**hl, "color": "red", "updated_at": _stamp(-7200)}
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [stale]}
    )
    [stored] = response.json()["highlights"]
    assert stored["color"] == "yellow"

    # Newer client copy wins.
    fresh = {**hl, "color": "blue", "updated_at": _stamp(3600)}
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [fresh]}
    )
    [stored] = response.json()["highlights"]
    assert stored["color"] == "blue"


async def test_sync_highlight_tombstone_union(admin_client, book_id):
    # Server-side highlight, deleted on the device: newer client tombstone
    # deletes the live server row.
    created = await admin_client.post(
        f"/api/books/{book_id}/highlights",
        json={"cfi_range": "epubcfi(/6/4!/4/2:0,/4/4:2)", "text": "web highlight"},
    )
    server_hl = created.json()
    tombstone = _sync_highlight(
        id=server_hl["id"],
        text=server_hl["text"],
        created_at=server_hl["created_at"],
        updated_at=_stamp(3600),
        deleted_at=_stamp(3600),
    )
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [tombstone]}
    )
    [stored] = response.json()["highlights"]
    assert stored["deleted_at"] is not None
    listing = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    assert listing == []

    # A stale live copy cannot resurrect the newer tombstone...
    stale_live = {
        **tombstone,
        "deleted_at": None,
        "updated_at": _stamp(-3600),
    }
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [stale_live]}
    )
    [stored] = response.json()["highlights"]
    assert stored["deleted_at"] is not None

    # ...but a newer edit revives it.
    revive = {**tombstone, "deleted_at": None, "updated_at": _stamp(7200)}
    await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [revive]}
    )
    listing = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    assert [h["id"] for h in listing] == [server_hl["id"]]


async def test_sync_highlight_foreign_id_skipped(admin_client, user_client, book_id):
    # Admin owns a highlight; another user syncing the same id must neither
    # touch it nor see it in the response.
    created = await admin_client.post(
        f"/api/books/{book_id}/highlights",
        json={"cfi_range": "epubcfi(/6/4!/4/6:0,/4/8:2)", "text": "admin's"},
    )
    admin_hl = created.json()

    foreign = _sync_highlight(
        id=admin_hl["id"], text="hijacked", updated_at=_stamp(3600)
    )
    response = await user_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [foreign]}
    )
    assert response.status_code == 200
    assert response.json()["highlights"] == []

    listing = (await admin_client.get(f"/api/books/{book_id}/highlights")).json()
    assert listing[0]["text"] == "admin's"


async def test_sync_highlight_duplicate_ids_in_one_request(admin_client, book_id):
    hl_id = str(uuid.uuid4())
    older = _sync_highlight(id=hl_id, color="yellow", updated_at=_stamp(-60))
    newer = _sync_highlight(id=hl_id, color="green", updated_at=_stamp())
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": [older, newer]}
    )
    assert response.status_code == 200
    [stored] = response.json()["highlights"]
    assert stored["color"] == "green"


async def test_sync_highlight_batch_cap(admin_client, book_id):
    items = [_sync_highlight() for _ in range(5001)]
    response = await admin_client.post(
        f"/api/books/{book_id}/sync", json={"highlights": items}
    )
    assert response.status_code == 422


async def test_sync_unknown_book_is_404(admin_client):
    response = await admin_client.post(
        f"/api/books/{uuid.uuid4()}/sync", json={}
    )
    assert response.status_code == 404


async def test_sync_respects_book_access(admin_client, user_client):
    lib = await create_library(admin_client, "Sync Hidden Lib")
    book = await upload_epub(admin_client, lib, title="Sync Hidden")
    user_id = await _user_id(admin_client, USER_CREDENTIALS["username"])
    await admin_client.put(
        f"/api/admin/users/{user_id}/library-access",
        json={"excluded_library_ids": [lib]},
    )
    response = await user_client.post(f"/api/books/{book['id']}/sync", json={})
    assert response.status_code == 403
