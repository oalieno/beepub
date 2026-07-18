from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_recompute_popularity_noop_on_empty():
    from app.services.popularity import recompute_popularity

    mock_db = AsyncMock()
    await recompute_popularity(mock_db, [])
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_recompute_popularity_runs_update_with_expected_params():
    from app.services.popularity import (
        CORROBORATION_BOOST,
        GOODREADS_RATING_COUNT_ANCHOR,
        HARDCOVER_RATING_COUNT_ANCHOR,
        HARDCOVER_USERS_READ_COUNT_ANCHOR,
        READMOO_RATING_COUNT_ANCHOR,
        recompute_popularity,
    )

    book_id = uuid.uuid4()
    mock_db = AsyncMock()
    await recompute_popularity(mock_db, [book_id])

    sql = str(mock_db.execute.call_args[0][0])
    params = mock_db.execute.call_args[0][1]
    assert params["book_ids"] == [str(book_id)]
    assert params["goodreads_anchor"] == GOODREADS_RATING_COUNT_ANCHOR
    assert params["readmoo_anchor"] == READMOO_RATING_COUNT_ANCHOR
    assert params["hardcover_rating_anchor"] == HARDCOVER_RATING_COUNT_ANCHOR
    assert params["hardcover_read_anchor"] == HARDCOVER_USERS_READ_COUNT_ANCHOR
    assert params["corroboration_boost"] == CORROBORATION_BOOST
    # Confirms cluster expansion + persistence shape
    assert "UPDATE books" in sql
    assert "popularity_score" in sql
    assert "work_id" in sql
    assert "series_key" in sql
    assert "source = 'goodreads'" in sql
    assert "source = 'readmoo'" in sql
    assert "source = 'hardcover'" in sql
    assert "source = 'google_books'" not in sql
    assert "readers_count" in sql
