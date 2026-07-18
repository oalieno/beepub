"""Unit tests for BookRecord storage serialization and the migration 054
raw_data -> record conversion (the frozen per-source knowledge)."""

import importlib.util
from pathlib import Path

from app.plugins.metadata import BookRecord
from app.plugins.metadata.base import RECORD_FIELDS
from app.services.metadata_fetch import RECORD_JSON_FIELDS, record_json


def test_record_json_holds_exactly_the_non_column_fields():
    # Columns (rating/rating_count/readers_count/reviews) + source_url
    # stay out of the JSONB; everything else goes in.
    assert set(RECORD_JSON_FIELDS) == RECORD_FIELDS - {
        "rating",
        "rating_count",
        "readers_count",
        "reviews",
    }

    record = BookRecord(
        source_url="https://example.com/book/1",
        title="神",
        authors=["董啟章"],
        publisher="聯經",
        tags=["fiction"],
        rating=4.2,
        rating_count=10,
        readers_count=99,
        reviews=[{"content": "great"}],
    )
    data = record_json(record)
    assert data["title"] == "神"
    assert data["tags"] == ["fiction"]
    assert "rating" not in data
    assert "source_url" not in data


def _load_migration_054():
    # Under pytest the local alembic/ migrations dir shadows the installed
    # lib, so `from alembic import op` inside the version module fails.
    # The module only needs the name to exist at import time — the pure
    # conversion function under test never touches op.
    import alembic

    if not hasattr(alembic, "op"):
        alembic.op = None

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "054_metadata_plugin_store.py"
    )
    spec = importlib.util.spec_from_file_location("migration_054", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_conversion_covers_all_legacy_sources():
    m = _load_migration_054()

    goodreads = m._record_from_raw(
        "goodreads", {"genres": ["Fantasy"], "shelves": ["to-read"]}
    )
    assert goodreads["tags"] == ["Fantasy", "to-read"]
    assert goodreads["description"] is None

    readmoo = m._record_from_raw("readmoo", {"categories": ["文學小說"]})
    assert readmoo["tags"] == ["文學小說"]

    google = m._record_from_raw(
        "google_books",
        {
            "categories": ["Fiction / Science Fiction"],
            "mainCategory": "Fiction",
            "description": "desc",
            "publishedDate": "2021-05-04",
            "language": "en",
            "pageCount": 496,
        },
    )
    assert google["tags"] == [
        "Fiction / Science Fiction",
        "Fiction",
        "Science Fiction",
        "Fiction",
    ]
    assert google["description"] == "desc"
    assert google["published_date"] == "2021-05-04"
    assert google["language"] == "en"

    hardcover = m._record_from_raw(
        "hardcover",
        {
            "genres": ["Science Fiction"],
            "moods": ["adventurous"],
            "tags": ["space"],
            "description": "desc",
            "release_date": "2021-05-04",
            "users_read_count": 12345,
        },
    )
    assert hardcover["tags"] == ["Science Fiction", "adventurous", "space"]
    assert hardcover["published_date"] == "2021-05-04"

    # The record shape always carries the full field set.
    for record in (goodreads, readmoo, google, hardcover):
        assert set(record) == {
            "title",
            "authors",
            "publisher",
            "description",
            "published_date",
            "language",
            "cover_url",
            "tags",
        }
