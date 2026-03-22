"""Semantic search API — cross-book search using pgvector embeddings."""

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
from app.services.embedding import embed_text
from app.services.settings import get_all_settings

router = APIRouter(prefix="/api/search", tags=["search"])


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


@router.get("/semantic", response_model=SemanticSearchResponse)
async def semantic_search(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(10, ge=1, le=50),
):
    """Search across all accessible books by semantic similarity."""
    from app.routers.libraries import accessible_libraries_condition

    # Load embedding settings
    settings = await get_all_settings(db)
    provider = settings.get("embedding_provider", "")
    model = settings.get("embedding_model", "")
    api_key = settings.get("gemini_api_key", "")

    if provider != "gemini" or not api_key or not model:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search is not configured",
        )

    # Embed the query
    query_vector, embed_usage = await embed_text(text=q, api_key=api_key, model=model)

    # Log usage (fire-and-forget)
    from app.services.llm_usage import log_llm_usage

    await log_llm_usage(
        feature="search",
        provider=provider,
        model=model,
        usage=embed_usage,
        user_id=current_user.id,
    )

    # Build accessible books subquery
    accessible_books = select(LibraryBook.book_id).join(
        Library, Library.id == LibraryBook.library_id
    )
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        accessible_books = accessible_books.where(cond)
    accessible_book_ids = accessible_books.subquery()

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


@router.post("/build-index", status_code=202)
async def trigger_build_search_index(
    _admin: Annotated[User, Depends(require_admin)],
):
    """Admin endpoint: trigger background build of the search index."""
    from app.tasks.embed import build_search_index

    build_search_index.delay()
    return {"status": "accepted", "message": "Search index build started"}
