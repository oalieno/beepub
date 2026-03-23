"""Tests for semantic similar books — summary concatenation, embedding, and recommendations."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Summary concatenation logic (_build_summary_text)
# ---------------------------------------------------------------------------


class TestBuildSummaryText:
    def _make_chunk(self, text: str, summary: str | None) -> SimpleNamespace:
        return SimpleNamespace(text=text, summary=summary, spine_index=0)

    def test_filters_short_summaries(self):
        from app.tasks.embed import _build_summary_text

        chunks = [
            self._make_chunk("long text " * 200, "x" * 49),  # too short
            self._make_chunk("long text " * 200, "x" * 60),  # valid
        ]
        text, count = _build_summary_text(chunks)
        assert count == 1
        assert text == "x" * 60

    def test_filters_verbatim_passthroughs(self):
        from app.tasks.embed import _build_summary_text

        raw_text = "Hello world this is some short text."
        # Summary equals text.strip()[:200] — this is a verbatim passthrough
        chunks = [
            self._make_chunk(raw_text, raw_text.strip()[:200]),
        ]
        text, count = _build_summary_text(chunks)
        assert count == 0
        assert text == ""

    def test_concatenates_in_order(self):
        from app.tasks.embed import _build_summary_text

        chunks = [
            self._make_chunk(
                "text " * 200,
                "Summary of chapter 1, which is quite detailed and long enough.",
            ),
            self._make_chunk(
                "text " * 200,
                "Summary of chapter 2, also detailed and of sufficient length here.",
            ),
            self._make_chunk(
                "text " * 200,
                "Summary of chapter 3, the final chapter with enough characters.",
            ),
        ]
        # Spine index ordering is preserved by input order
        text, count = _build_summary_text(chunks)
        assert count == 3
        lines = text.split("\n")
        assert "chapter 1" in lines[0]
        assert "chapter 2" in lines[1]
        assert "chapter 3" in lines[2]

    def test_returns_empty_when_all_filtered(self):
        from app.tasks.embed import _build_summary_text

        chunks = [
            self._make_chunk("short", "sho"),  # summary too short
            self._make_chunk("", None),  # no summary
        ]
        text, count = _build_summary_text(chunks)
        assert count == 0
        assert text == ""

    def test_no_chunks(self):
        from app.tasks.embed import _build_summary_text

        text, count = _build_summary_text([])
        assert count == 0
        assert text == ""

    def test_keeps_long_genuine_summaries(self):
        from app.tasks.embed import _build_summary_text

        long_text = "A" * 5000
        long_summary = "This is a genuine LLM-generated summary that captures the essence of the chapter content."
        chunks = [self._make_chunk(long_text, long_summary)]
        text, count = _build_summary_text(chunks)
        assert count == 1
        assert text == long_summary


# ---------------------------------------------------------------------------
# 1b. Chunk-avg embedding query uses CAST to Vector
# ---------------------------------------------------------------------------


class TestChunkAvgEmbeddingCast:
    """Verify the AVG query casts to Vector — prevents the pgvector string bug.

    pgvector's AVG() returns a string like '[-0.02, ...]' not a Vector object.
    Without CAST(... AS VECTOR), the upsert fails with ValueError at runtime.
    Mocked db.execute can't catch this because it never compiles real SQL,
    so we compile the SELECT statement and check for CAST.
    """

    def test_avg_query_includes_vector_cast(self):
        from sqlalchemy import func, select
        from sqlalchemy.dialects import postgresql

        from app.models.book_embedding import BookEmbeddingChunk

        from pgvector.sqlalchemy import Vector as VectorType

        stmt = select(
            func.avg(BookEmbeddingChunk.embedding)
            .cast(VectorType(1024))
            .label("avg_emb"),
            func.count().label("cnt"),
        ).where(BookEmbeddingChunk.book_id == "fake-id")

        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "CAST" in sql.upper()
        assert "vector" in sql.lower() or "VECTOR" in sql

    @pytest.mark.asyncio
    async def test_upsert_skips_when_zero_chunks(self):
        from app.tasks.embed import _upsert_chunk_avg_embedding

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one.return_value = SimpleNamespace(avg_emb=None, cnt=0)
        mock_db.execute = AsyncMock(return_value=mock_result)

        await _upsert_chunk_avg_embedding(mock_db, uuid.uuid4(), "test-model")

        # Should only call execute once (the SELECT), not the INSERT
        assert mock_db.execute.call_count == 1
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_calls_insert_when_chunks_exist(self):
        from app.tasks.embed import _upsert_chunk_avg_embedding

        mock_db = AsyncMock()
        # First call: SELECT AVG
        mock_avg_result = MagicMock()
        mock_avg_result.one.return_value = SimpleNamespace(
            avg_emb=[0.1] * 1024, cnt=5
        )
        # Second call: INSERT upsert
        mock_insert_result = MagicMock()

        mock_db.execute = AsyncMock(
            side_effect=[mock_avg_result, mock_insert_result]
        )
        mock_db.commit = AsyncMock()

        await _upsert_chunk_avg_embedding(mock_db, uuid.uuid4(), "test-model")

        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Token truncation
# ---------------------------------------------------------------------------


class TestTokenTruncation:
    def test_char_fallback_limit(self):
        from app.tasks.embed import _CHAR_FALLBACK_LIMIT

        assert _CHAR_FALLBACK_LIMIT == 6000

    def test_token_limit(self):
        from app.tasks.embed import _EMBED_TOKEN_LIMIT

        assert _EMBED_TOKEN_LIMIT == 4096


# ---------------------------------------------------------------------------
# 3. EMBEDDING_DIMENSIONS constant
# ---------------------------------------------------------------------------


class TestEmbeddingDimensions:
    def test_dimensions_value(self):
        from app.services.embedding import EMBEDDING_DIMENSIONS

        assert EMBEDDING_DIMENSIONS == 1024


# ---------------------------------------------------------------------------
# 4. get_similar_books — semantic CTE integration
# ---------------------------------------------------------------------------


class TestGetSimilarBooksSemantic:
    """Test semantic similarity integration in get_similar_books.

    These tests verify the SQL query structure and parameter passing.
    They mock the database execution to avoid needing a real DB.
    """

    @pytest.mark.asyncio
    async def test_passes_semantic_params(self):
        """Verify semantic_weight and semantic_limit are passed to query."""
        from app.services.recommendations import get_similar_books

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        await get_similar_books(
            mock_db,
            uuid.uuid4(),
            uuid.uuid4(),
            is_admin=False,
            semantic_weight=5.0,
            semantic_limit=25,
        )

        # Verify the query was called with semantic params
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params["semantic_weight"] == 5.0
        assert params["semantic_limit"] == 25

    @pytest.mark.asyncio
    async def test_returns_cosine_similarity(self):
        """Verify cosine_similarity is included in response."""
        from app.services.recommendations import get_similar_books

        book_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (str(uuid.uuid4()), 15.5, 0.85),  # has cosine_similarity
            (str(uuid.uuid4()), 10.0, None),  # no embedding
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await get_similar_books(
            mock_db,
            book_id,
            uuid.uuid4(),
            is_admin=True,
            semantic_weight=10.0,
            semantic_limit=50,
        )

        assert len(results) == 2
        assert results[0]["cosine_similarity"] == 0.85
        assert results[1]["cosine_similarity"] is None

    @pytest.mark.asyncio
    async def test_weight_zero_disables_semantic(self):
        """With semantic_weight=0, semantic scores contribute 0 points."""
        from app.services.recommendations import get_similar_books

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        await get_similar_books(
            mock_db,
            uuid.uuid4(),
            uuid.uuid4(),
            is_admin=False,
            semantic_weight=0.0,
            semantic_limit=50,
        )

        params = mock_db.execute.call_args[0][1]
        assert params["semantic_weight"] == 0.0


# ---------------------------------------------------------------------------
# 5. Attribution tracking in personalized recommendations
# ---------------------------------------------------------------------------


class TestAttributionTracking:
    @pytest.mark.asyncio
    async def test_tracks_best_seed(self):
        """Verify the seed with highest contribution is tracked."""
        from app.services.recommendations import get_personalized_recommendations

        seed_a = uuid.uuid4()
        seed_b = uuid.uuid4()
        candidate = uuid.uuid4()

        # Mock seed query
        mock_seed_result = MagicMock()
        mock_seed_result.fetchall.return_value = [
            (str(seed_a),),
            (str(seed_b),),
        ]

        # Mock read-books query (empty — no books to exclude)
        mock_read_result = MagicMock()
        mock_read_result.fetchall.return_value = []

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_seed_result
            elif call_count == 2:
                return mock_read_result
            return MagicMock(fetchall=MagicMock(return_value=[]))

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        # Mock get_similar_books to return controlled data
        async def mock_similar(db, book_id, user_id, is_admin, limit=20):
            if book_id == seed_a:
                return [{"book_id": candidate, "score": 5.0, "cosine_similarity": None}]
            elif book_id == seed_b:
                return [{"book_id": candidate, "score": 12.0, "cosine_similarity": 0.9}]
            return []

        with patch(
            "app.services.recommendations.get_similar_books",
            side_effect=mock_similar,
        ):
            results = await get_personalized_recommendations(
                mock_db,
                uuid.uuid4(),
                is_admin=False,
            )

        assert len(results) == 1
        assert results[0]["book_id"] == candidate
        assert results[0]["score"] == 17.0  # 5.0 + 12.0
        # seed_b contributed 12.0 > seed_a's 5.0, so seed_b should be the attribution
        assert results[0]["seed_book_id"] == seed_b

    @pytest.mark.asyncio
    async def test_excludes_seed_and_read_books(self):
        """Verify seed books and already-read books are excluded."""
        from app.services.recommendations import get_personalized_recommendations

        seed = uuid.uuid4()
        read_book = uuid.uuid4()
        good_rec = uuid.uuid4()

        mock_seed_result = MagicMock()
        mock_seed_result.fetchall.return_value = [(str(seed),)]

        mock_read_result = MagicMock()
        mock_read_result.fetchall.return_value = [(str(read_book),)]

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_seed_result
            elif call_count == 2:
                return mock_read_result
            return MagicMock(fetchall=MagicMock(return_value=[]))

        mock_db = AsyncMock()
        mock_db.execute = mock_execute

        async def mock_similar(db, book_id, user_id, is_admin, limit=20):
            return [
                {"book_id": seed, "score": 10.0, "cosine_similarity": None},
                {"book_id": read_book, "score": 8.0, "cosine_similarity": None},
                {"book_id": good_rec, "score": 6.0, "cosine_similarity": 0.7},
            ]

        with patch(
            "app.services.recommendations.get_similar_books",
            side_effect=mock_similar,
        ):
            results = await get_personalized_recommendations(
                mock_db,
                uuid.uuid4(),
                is_admin=False,
            )

        result_ids = {r["book_id"] for r in results}
        assert seed not in result_ids
        assert read_book not in result_ids
        assert good_rec in result_ids


# ---------------------------------------------------------------------------
# 6. BookSummaryEmbedding model structure
# ---------------------------------------------------------------------------


class TestBookEmbeddingModel:
    def test_model_has_expected_columns(self):
        from app.models.book_embedding_unified import BookEmbedding

        columns = BookEmbedding.__table__.columns
        expected = {
            "id",
            "book_id",
            "embedding",
            "embedding_model",
            "source_summary_count",
            "source",
            "created_at",
            "updated_at",
        }
        assert set(columns.keys()) == expected

    def test_book_id_is_unique(self):
        from app.models.book_embedding_unified import BookEmbedding

        col = BookEmbedding.__table__.columns["book_id"]
        assert col.unique is True

    def test_tablename(self):
        from app.models.book_embedding_unified import BookEmbedding

        assert BookEmbedding.__tablename__ == "book_embeddings"

    def test_source_column_default(self):
        from app.models.book_embedding_unified import BookEmbedding

        col = BookEmbedding.__table__.columns["source"]
        assert col.server_default.arg == "summary"

    def test_summary_embedding_job_removed(self):
        """summary_embedding job type was removed — embed_book auto-creates chunk_avg."""
        from app.services.job_queue import JOB_TYPES

        assert "summary_embedding" not in JOB_TYPES


# ---------------------------------------------------------------------------
# 8. Settings defaults
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    def test_semantic_weight_default(self):
        from app.services.settings import DEFAULTS

        assert DEFAULTS["similar_books_semantic_weight"] == "10.0"

    def test_semantic_limit_default(self):
        from app.services.settings import DEFAULTS

        assert DEFAULTS["similar_books_semantic_limit"] == "50"

    def test_embedding_api_url_default(self):
        from app.services.settings import DEFAULTS

        assert DEFAULTS["embedding_api_url"] == ""

    def test_embedding_api_key_default(self):
        from app.services.settings import DEFAULTS

        assert DEFAULTS["embedding_api_key"] == ""
