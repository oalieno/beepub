"""An upload built to unpack without end is refused before it is unpacked."""

import io
import zipfile

import pytest

from app.config import settings
from app.services import ingest
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


def _stored_files() -> set[str]:
    import os

    found = set()
    for directory in (settings.books_dir, settings.covers_dir):
        for root, _dirs, files in os.walk(directory):
            found.update(os.path.join(root, name) for name in files)
    return found


def _archive_of_zeros(megabytes: int) -> bytes:
    """A small zip holding one entry of zeros — which pack to almost nothing."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("OEBPS/chapter.xhtml", b"\0" * (megabytes * 1024 * 1024))
    return buffer.getvalue()


@pytest.mark.parametrize("name", ["book.epub", "book.cbz"])
async def test_an_archive_that_unpacks_too_large_is_refused(
    admin_client, monkeypatch, name
):
    library_id = await create_library(admin_client)
    # (The real limits are gigabytes; the rule is the same at 8 MB.)
    monkeypatch.setattr(ingest, "MAX_UNPACKED_SIZE", 8 * 1024 * 1024)
    before = _stored_files()
    bomb = _archive_of_zeros(16)
    assert len(bomb) < 64 * 1024

    response = await admin_client.post(
        "/api/books",
        files={"file": (name, bomb, "application/zip")},
        data={"library_id": library_id},
    )

    assert response.status_code == 413, response.text
    assert _stored_files() == before  # nothing of it is kept


async def test_an_ordinary_book_is_not(admin_client, monkeypatch):
    library_id = await create_library(admin_client)
    monkeypatch.setattr(ingest, "MAX_UNPACKED_SIZE", 8 * 1024 * 1024)
    book = await upload_epub(admin_client, library_id)
    assert book["id"]
