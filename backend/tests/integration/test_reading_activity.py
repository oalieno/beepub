"""Device-scoped reading activity: aggregation and the web accumulator.

Devices each own (user_id, device_id, date) rows; the readers must
aggregate per date — the streak helpers require DISTINCT dates, and the
heatmap shows one summed cell per day.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


def _app_today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


async def _seed_activity(username: str, rows: list[tuple[str, object, int]]):
    """Insert (device_id, date, seconds) rows for the user directly —
    cross-device rows can't be created through the API in this commit."""
    from sqlalchemy import insert, select

    from app.database import engine
    from app.models.reading import ReadingActivity
    from app.models.user import User

    async with engine.begin() as conn:
        user_id = (
            await conn.execute(select(User.id).where(User.username == username))
        ).scalar_one()
        await conn.execute(
            insert(ReadingActivity),
            [
                {
                    "user_id": user_id,
                    "device_id": device_id,
                    "date": day,
                    "seconds": seconds,
                }
                for device_id, day, seconds in rows
            ],
        )


async def test_heatmap_sums_across_devices(admin_client):
    today = _app_today()
    await _seed_activity(
        "admin",
        [("web", today, 120), ("device-a", today, 300), ("device-b", today, 60)],
    )
    response = await admin_client.get("/api/books/reading-activity")
    assert response.status_code == 200
    entries = [e for e in response.json() if e["date"] == today.isoformat()]
    assert entries == [{"date": today.isoformat(), "seconds": 480}]


async def test_stats_counts_shared_date_once(admin_client):
    today = _app_today()
    yesterday = today - timedelta(days=1)
    await _seed_activity(
        "admin",
        [("web", today, 100), ("device-a", today, 200), ("device-a", yesterday, 50)],
    )
    stats = (await admin_client.get("/api/books/reading-stats")).json()
    assert stats["current_streak"] == 2
    assert stats["today_seconds"] == 300


async def test_longest_streak_unbroken_by_duplicate_dates(admin_client):
    # Three consecutive days; the middle one recorded on two devices. A
    # duplicate date used to reset the longest-streak walk.
    today = _app_today()
    await _seed_activity(
        "admin",
        [
            ("web", today - timedelta(days=2), 60),
            ("web", today - timedelta(days=1), 60),
            ("device-a", today - timedelta(days=1), 60),
            ("web", today, 60),
        ],
    )
    stats = (await admin_client.get("/api/books/reading-stats")).json()
    assert stats["longest_streak"] == 3


async def test_web_accumulator_lands_in_web_row(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    book_id = book["id"]

    first = await admin_client.put(
        f"/api/books/{book_id}/progress", json={"cfi": "epubcfi(/6/2!/4/2)"}
    )
    assert first.status_code == 200
    # The accumulator credits the gap between two user-driven saves.
    await asyncio.sleep(0.1)
    second = await admin_client.put(
        f"/api/books/{book_id}/progress", json={"cfi": "epubcfi(/6/2!/4/4)"}
    )
    assert second.status_code == 200

    from sqlalchemy import select

    from app.database import engine
    from app.models.reading import ReadingActivity

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(ReadingActivity.device_id, ReadingActivity.seconds)
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].device_id == "web"
    assert rows[0].seconds >= 0


def _entry(day, seconds: int) -> dict:
    return {"date": day.isoformat(), "seconds": seconds}


async def test_activity_sync_replaces_not_accumulates(admin_client):
    today = _app_today()
    first = await admin_client.post(
        "/api/activity/sync",
        json={"device_id": "device-a", "entries": [_entry(today, 900)]},
    )
    assert first.status_code == 200
    assert first.json() == {"days": 1}

    # Re-pushing the same day sets its value — idempotent under replays.
    second = await admin_client.post(
        "/api/activity/sync",
        json={"device_id": "device-a", "entries": [_entry(today, 1200)]},
    )
    assert second.status_code == 200

    activity = (await admin_client.get("/api/books/reading-activity")).json()
    entries = [e for e in activity if e["date"] == today.isoformat()]
    assert entries == [{"date": today.isoformat(), "seconds": 1200}]


async def test_activity_sync_rejects_web_device(admin_client):
    today = _app_today()
    for device_id in ("web", "WEB", " web "):
        response = await admin_client.post(
            "/api/activity/sync",
            json={"device_id": device_id, "entries": [_entry(today, 60)]},
        )
        assert response.status_code == 422


async def test_activity_sync_merges_with_web_rows(admin_client):
    today = _app_today()
    yesterday = today - timedelta(days=1)
    await _seed_activity("admin", [("web", today, 300)])
    response = await admin_client.post(
        "/api/activity/sync",
        json={
            "device_id": "device-a",
            "entries": [_entry(today, 600), _entry(yesterday, 60)],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"days": 2}

    stats = (await admin_client.get("/api/books/reading-stats")).json()
    assert stats["today_seconds"] == 900
    assert stats["current_streak"] == 2


async def test_activity_sync_requires_auth(client):
    response = await client.post(
        "/api/activity/sync", json={"device_id": "device-a", "entries": []}
    )
    assert response.status_code == 401


async def test_activity_sync_validates_bounds(admin_client):
    today = _app_today()
    over_cap = await admin_client.post(
        "/api/activity/sync",
        json={"device_id": "device-a", "entries": [_entry(today, 90000)]},
    )
    assert over_cap.status_code == 422

    empty = await admin_client.post(
        "/api/activity/sync", json={"device_id": "device-a", "entries": []}
    )
    assert empty.status_code == 200
    assert empty.json() == {"days": 0}
