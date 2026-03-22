"""Celery tasks for embedding book text chunks into vectors."""

from __future__ import annotations

import logging
import uuid

from app.celeryapp import celery

logger = logging.getLogger(__name__)

# Max texts per Gemini batchEmbedContents call
_EMBED_BATCH_SIZE = 100


@celery.task(
    name="app.tasks.embed.embed_book",
    bind=True,
    max_retries=3,
)
def embed_book(self, book_id: str) -> None:
    """Embed all text chunks of a book into BookEmbeddingChunk rows.

    Idempotent at chunk level — skips sub-chunks that already have embeddings.
    """
    import asyncio

    async def _run() -> None:
        from sqlalchemy import select

        from app.database import create_task_session
        from app.models.book_embedding import BookEmbeddingChunk
        from app.models.book_text import BookTextChunk
        from app.services.embedding import embed_texts
        from app.services.settings import get_all_settings
        from app.services.text_chunking import split_text_into_chunks

        session_factory = create_task_session()
        async with session_factory() as db:
            bid = uuid.UUID(book_id)

            # Load settings for embedding config
            settings = await get_all_settings(db)
            provider = settings.get("embedding_provider", "")
            model = settings.get("embedding_model", "")
            api_key = settings.get("gemini_api_key", "")

            if provider != "gemini" or not api_key or not model:
                logger.warning(
                    "Embedding not configured (provider=%s, model=%s), skipping book %s",
                    provider,
                    model,
                    book_id,
                )
                return

            # Get all text chunks for this book
            result = await db.execute(
                select(BookTextChunk)
                .where(BookTextChunk.book_id == bid)
                .order_by(BookTextChunk.spine_index)
            )
            text_chunks = list(result.scalars().all())

            if not text_chunks:
                logger.info("Book %s has no text chunks, skipping embedding", book_id)
                return

            total_embedded = 0

            for text_chunk in text_chunks:
                sub_chunks = split_text_into_chunks(text_chunk.text)
                if not sub_chunks:
                    continue

                # Check which sub-chunks already exist (idempotent)
                existing = await db.execute(
                    select(BookEmbeddingChunk.chunk_index).where(
                        BookEmbeddingChunk.book_text_chunk_id == text_chunk.id
                    )
                )
                existing_indices = {row[0] for row in existing.all()}

                # Filter to only new sub-chunks
                new_sub_chunks = [
                    sc for sc in sub_chunks if sc.chunk_index not in existing_indices
                ]
                if not new_sub_chunks:
                    continue

                # Batch embed
                for i in range(0, len(new_sub_chunks), _EMBED_BATCH_SIZE):
                    batch = new_sub_chunks[i : i + _EMBED_BATCH_SIZE]
                    texts = [sc.text for sc in batch]

                    vectors, usage = await embed_texts(
                        texts, api_key=api_key, model=model
                    )

                    for sc, vector in zip(batch, vectors):
                        db.add(
                            BookEmbeddingChunk(
                                book_id=bid,
                                book_text_chunk_id=text_chunk.id,
                                spine_index=text_chunk.spine_index,
                                chunk_index=sc.chunk_index,
                                text=sc.text,
                                char_offset_start=sc.char_offset_start,
                                char_offset_end=sc.char_offset_end,
                                embedding=vector,
                                embedding_model=model,
                            )
                        )

                    await db.commit()
                    total_embedded += len(batch)

                    # Log usage (fire-and-forget)
                    from app.services.llm_usage import log_llm_usage

                    await log_llm_usage(
                        feature="embedding",
                        provider=provider,
                        model=model,
                        usage=usage,
                        book_id=bid,
                        session_factory=session_factory,
                    )

            logger.info("Embedded %d sub-chunks for book %s", total_embedded, book_id)

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.exception("embed_book failed for book %s", book_id)
        raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))


@celery.task(
    name="app.tasks.embed.build_search_index",
    bind=True,
)
def build_search_index(self, batch_size: int = 10) -> None:
    """Legacy wrapper — delegates to the unified bulk job system."""
    from app.tasks.bulk_jobs import run_bulk_job

    run_bulk_job("embedding", "missing")
