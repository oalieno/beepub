"""Search API — semantic (pgvector) and keyword (pg_trgm ILIKE) search."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book
from app.models.book_embedding import BookEmbeddingChunk
from app.models.library import Library, LibraryBook
from app.models.user import User
from app.services.embedding import EMBEDDING_PROMPT_QUERY, embed_text
from app.services.settings import get_all_settings

router = APIRouter(prefix="/api/search", tags=["search"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _accessible_book_ids_subquery(user: User):
    """Build a subquery of book IDs the user is allowed to access."""
    from app.routers.libraries import accessible_libraries_condition

    stmt = select(LibraryBook.book_id).join(
        Library, Library.id == LibraryBook.library_id
    )
    cond = accessible_libraries_condition(user)
    if cond is not True:
        stmt = stmt.where(cond)
    return stmt.subquery()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SemanticSearchResult(BaseModel):
    book_id: str
    book_title: str
    book_author: str | None
    passage: str
    spine_index: int
    char_offset_start: int
    char_offset_end: int
    similarity: float


class SemanticSearchResponse(BaseModel):
    results: list[SemanticSearchResult]
    query: str


class KeywordSearchResult(BaseModel):
    book_id: str
    book_title: str
    book_author: str | None
    passage: str
    spine_index: int
    char_offset_start: int
    char_offset_end: int


class KeywordSearchResponse(BaseModel):
    results: list[KeywordSearchResult]
    query: str
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/semantic", response_model=SemanticSearchResponse)
async def semantic_search(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(10, ge=1, le=50),
):
    """Search across all accessible books by semantic similarity."""
    # Load embedding settings
    settings = await get_all_settings(db)
    api_url = settings.get("embedding_api_url", "")
    model = settings.get("embedding_model", "")
    api_key = settings.get("embedding_api_key", "")

    if not api_url or not model:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search is not configured",
        )

    # Embed the query
    query_vector, embed_usage = await embed_text(
        text=q,
        api_url=api_url,
        model=model,
        api_key=api_key,
        prompt=EMBEDDING_PROMPT_QUERY,
    )

    # Log usage (fire-and-forget)
    from app.services.llm_usage import log_llm_usage

    await log_llm_usage(
        feature="search",
        provider="openai_compatible",
        model=model,
        usage=embed_usage,
        user_id=current_user.id,
    )

    accessible_book_ids = _accessible_book_ids_subquery(current_user)

    # Vector similarity search with access control pre-filter
    import numpy as np

    query_vec = np.array(query_vector, dtype=np.float32)

    stmt = (
        select(
            BookEmbeddingChunk.book_id,
            BookEmbeddingChunk.text,
            BookEmbeddingChunk.spine_index,
            BookEmbeddingChunk.char_offset_start,
            BookEmbeddingChunk.char_offset_end,
            (1 - BookEmbeddingChunk.embedding.cosine_distance(query_vec)).label(
                "similarity"
            ),
            func.coalesce(Book.title, Book.epub_title).label("display_title"),
            func.coalesce(Book.authors, Book.epub_authors).label("display_authors"),
        )
        .join(Book, Book.id == BookEmbeddingChunk.book_id)
        .where(BookEmbeddingChunk.book_id.in_(select(accessible_book_ids)))
        .order_by(BookEmbeddingChunk.embedding.cosine_distance(query_vec))
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    results = [
        SemanticSearchResult(
            book_id=str(row.book_id),
            book_title=row.display_title or "Untitled",
            book_author=", ".join(row.display_authors) if row.display_authors else None,
            passage=row.text,
            spine_index=row.spine_index,
            char_offset_start=row.char_offset_start,
            char_offset_end=row.char_offset_end,
            similarity=round(float(row.similarity), 4),
        )
        for row in rows
    ]

    return SemanticSearchResponse(results=results, query=q)


@router.get("/keyword", response_model=KeywordSearchResponse)
async def keyword_search(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(10, ge=1, le=50),
):
    """Search across all accessible books by exact keyword match (ILIKE + pg_trgm)."""
    accessible_book_ids = _accessible_book_ids_subquery(current_user)
    pattern = f"%{q}%"

    # Count total matches (capped for performance)
    count_stmt = (
        select(func.count())
        .select_from(BookEmbeddingChunk)
        .where(
            BookEmbeddingChunk.book_id.in_(select(accessible_book_ids)),
            BookEmbeddingChunk.text.ilike(pattern),
        )
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch results
    stmt = (
        select(
            BookEmbeddingChunk.book_id,
            BookEmbeddingChunk.text,
            BookEmbeddingChunk.spine_index,
            BookEmbeddingChunk.char_offset_start,
            BookEmbeddingChunk.char_offset_end,
            func.coalesce(Book.title, Book.epub_title).label("display_title"),
            func.coalesce(Book.authors, Book.epub_authors).label("display_authors"),
        )
        .join(Book, Book.id == BookEmbeddingChunk.book_id)
        .where(
            BookEmbeddingChunk.book_id.in_(select(accessible_book_ids)),
            BookEmbeddingChunk.text.ilike(pattern),
        )
        .order_by(Book.title, BookEmbeddingChunk.spine_index)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    results = [
        KeywordSearchResult(
            book_id=str(row.book_id),
            book_title=row.display_title or "Untitled",
            book_author=", ".join(row.display_authors) if row.display_authors else None,
            passage=row.text,
            spine_index=row.spine_index,
            char_offset_start=row.char_offset_start,
            char_offset_end=row.char_offset_end,
        )
        for row in rows
    ]

    return KeywordSearchResponse(results=results, query=q, total=total)


@router.post("/build-index", status_code=202)
async def trigger_build_search_index(
    _admin: Annotated[User, Depends(require_admin)],
):
    """Admin endpoint: trigger background build of the search index."""
    from app.tasks.embed import build_search_index

    build_search_index.delay()
    return {"status": "accepted", "message": "Search index build started"}
