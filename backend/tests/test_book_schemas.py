"""BookMetadataUpdate.field_sources — the provenance map only accepts
the overridable fields (plus "cover") and sane source names."""

import pytest
from pydantic import ValidationError

from app.schemas.book import BookMetadataUpdate


def test_field_sources_accepts_known_fields_and_cover():
    update = BookMetadataUpdate(
        field_sources={
            "title": "manual",
            "description": "readmoo",
            "cover": "google_books",
        }
    )
    assert update.field_sources == {
        "title": "manual",
        "description": "readmoo",
        "cover": "google_books",
    }


def test_field_sources_rejects_unknown_field():
    with pytest.raises(ValidationError):
        BookMetadataUpdate(field_sources={"word_count": "manual"})


def test_field_sources_rejects_empty_and_oversized_sources():
    with pytest.raises(ValidationError):
        BookMetadataUpdate(field_sources={"title": ""})
    with pytest.raises(ValidationError):
        BookMetadataUpdate(field_sources={"title": "x" * 51})
