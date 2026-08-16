"""BookOut.section_weights — per-section text sizes derived from text chunks.

The reader interpolates reading percentage from these weights instead of
generating epub.js locations, so the contract under test is: absent until
extraction has run, then a dense-by-spine-index array proportional to each
section's text size.
"""

import pytest
from httpx import AsyncClient

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration


async def test_section_weights_absent_before_extraction(
    admin_client: AsyncClient,
):
    library_id = await create_library(admin_client, "Weights Pending")
    book = await upload_epub(
        admin_client,
        library_id,
        identifier="urn:uuid:00000000-0000-4000-8000-000000000201",
    )
    detail = (await admin_client.get(f"/api/books/{book['id']}")).json()
    assert detail["section_weights"] is None


async def test_section_weights_follow_spine_text_sizes(
    admin_client: AsyncClient,
):
    library_id = await create_library(admin_client, "Weights Sized")
    book = await upload_epub(
        admin_client,
        library_id,
        identifier="urn:uuid:00000000-0000-4000-8000-000000000202",
        chapters=[
            ("Big", ["甲" * 400] * 10),
            ("Small", ["乙" * 40]),
        ],
    )

    from app.tasks.text_extract import _run_extract_book_text

    await _run_extract_book_text(book["id"])

    detail = (await admin_client.get(f"/api/books/{book['id']}")).json()
    weights = detail["section_weights"]
    assert weights is not None

    # Exactly the two text chapters carry weight; cover/nav spine slots are
    # zero-filled, keeping indices aligned with the OPF spine order.
    nonzero = [w for w in weights if w > 0]
    assert len(nonzero) == 2
    big, small = sorted(nonzero, reverse=True)
    # 4000 chars vs 40 — assert proportionality loosely, not exact counts
    # (extraction may include chapter titles/whitespace).
    assert big > small * 5
