"""Unschemed dc:identifier values only count as ISBNs with a valid check
digit (Kindle files carry a random 10-digit uid)."""

import pytest

from app.services.epub_parser import is_valid_isbn


@pytest.mark.parametrize(
    "value",
    ["0306406152", "0-306-40615-2", "080442957X", "9780306406157", "978-0-306-40615-7"],
)
def test_valid_isbns(value):
    assert is_valid_isbn(value)


@pytest.mark.parametrize(
    "value",
    ["2551844346", "0306406153", "9780306406158", "12345", "urn:uuid:abc", ""],
)
def test_invalid_isbns(value):
    assert not is_valid_isbn(value)
