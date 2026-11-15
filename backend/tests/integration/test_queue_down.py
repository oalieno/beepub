"""The background queue is unreachable: what was saved stays saved.

Work that only follows up something already committed (extract a book's
text, fetch its metadata) is queued after the commit. With the queue
down, queueing fails — and that used to turn a request that had already
succeeded into a 500.
"""

import pytest
from kombu.exceptions import OperationalError

from app.config import settings
from app.tasks.metadata import fetch_book_metadata
from app.tasks.text_extract import extract_book_text
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


@pytest.fixture
def queue_down(monkeypatch):
    refused = []

    def refuse(*args, **kwargs):
        refused.append(args)
        raise OperationalError("Error 111 connecting to redis. Connection refused.")

    for task in (extract_book_text, fetch_book_metadata):
        monkeypatch.setattr(task, "delay", refuse)
    return refused


async def test_a_position_is_saved_with_the_queue_down(admin_client, queue_down):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)
    assert book["id"]  # (the upload itself got through as well)
    queued_by_upload = len(queue_down)
    assert queued_by_upload == 2

    payload = {"cfi": "epubcfi(/6/4!/4/2/1:0)", "percentage": 12.5, "section_index": 1}
    response = await admin_client.put(f"/api/books/{book['id']}/progress", json=payload)
    assert response.status_code == 200, response.text
    assert len(queue_down) > queued_by_upload  # (it did try to queue)

    progress = (await admin_client.get(f"/api/books/{book['id']}/progress")).json()
    assert progress["percentage"] == 12.5


async def test_ready_says_which_dependency_is_down(client, monkeypatch):
    response = await client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True, "queue": True}

    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1")
    response = await client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": True,
        "queue": False,
    }
    # The plain check is about the server alone, and stays as it was.
    assert (await client.get("/api/health")).status_code == 200
