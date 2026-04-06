"""Celery tasks for embedding book text chunks into vectors."""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import func

from app.celeryapp import celery

logger = logging.getLogger(__name__)

# Max texts per batch embedding call
_EMBED_BATCH_SIZE = 100
# Skip text chunks shorter than this — page numbers, titles, dedications, etc.
# produce low-quality embeddings and waste API calls.
_MIN_CHUNK_CHARS = 200


async def _run_embed_book(book_id: str) -> None:
    """Embed all text chunks of a book into BookEmbeddingChunk rows.

    Idempotent at chunk level — skips sub-chunks that already have embeddings.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    from app.database import create_task_engine
    from app.models.book import Book
    from app.models.book_embedding import BookEmbeddingChunk
    from app.models.book_text import BookTextChunk
    from app.services.embedding import embed_texts
    from app.services.settings import get_all_settings
    from app.services.text_chunking import split_text_into_chunks

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            bid = uuid.UUID(book_id)

            # Skip image books — no meaningful text to embed
            img_result = await db.execute(
                select(Book.is_image_book).where(Book.id == bid)
            )
            if img_result.scalar_one_or_none() is True:
                logger.info(f"Book {book_id} is an image book, skipping embedding")
                return

            # Load settings for embedding config
            settings = await get_all_settings(db)
            api_url = settings.get("embedding_api_url", "")
            model = settings.get("embedding_model", "")
            api_key = settings.get("embedding_api_key", "")

            if not api_url or not model:
                logger.warning(
                    f"Embedding not configured (api_url={api_url}, model={model}), skipping book {book_id}"
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
                logger.info(f"Book {book_id} has no text chunks, skipping embedding")
                return

            total_embedded = 0

            for text_chunk in text_chunks:
                if len(text_chunk.text.strip()) < _MIN_CHUNK_CHARS:
                    continue
                sub_chunks = split_text_into_chunks(text_chunk.text)
                if not sub_chunks:
                    continue

                # Batch embed — use ON CONFLICT DO NOTHING for race-safe idempotency
                for i in range(0, len(sub_chunks), _EMBED_BATCH_SIZE):
                    batch = sub_chunks[i : i + _EMBED_BATCH_SIZE]
                    cleaned = [
                        (sc, re.sub(r"\s+", " ", sc.text).strip()) for sc in batch
                    ]
                    cleaned = [(sc, t) for sc, t in cleaned if t]
                    if not cleaned:
                        continue
                    batch, texts = zip(*cleaned)  # type: ignore[assignment]

                    vectors, usage = await embed_texts(
                        texts, api_url=api_url, model=model, api_key=api_key
                    )

                    for sc, vector in zip(batch, vectors):
                        stmt = insert(BookEmbeddingChunk).values(
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
                        stmt = stmt.on_conflict_do_nothing(
                            index_elements=["book_text_chunk_id", "chunk_index"],
                        )
                        await db.execute(stmt)

                    await db.commit()
                    total_embedded += len(batch)

                    # Log usage (fire-and-forget)
                    from app.services.llm_usage import log_llm_usage

                    await log_llm_usage(
                        feature="embedding",
                        provider="openai_compatible",
                        model=model,
                        usage=usage,
                        book_id=bid,
                        session_factory=session_factory,
                    )

            logger.info(f"Embedded {total_embedded} sub-chunks for book {book_id}")

            # Compute book-level average embedding from chunks
            if total_embedded > 0:
                await _upsert_chunk_avg_embedding(db, bid, model)

                # Mark book as having an embedding
                from sqlalchemy import update

                await db.execute(
                    update(Book).where(Book.id == bid).values(has_embedding=True)
                )
                await db.commit()


@celery.task(
    name="app.tasks.embed.embed_book",
    bind=True,
    max_retries=5,
    rate_limit="10/m",
)
def embed_book(self, book_id: str) -> None:
    """Celery wrapper for _run_embed_book."""
    try:
        from app.celeryapp import run_async

        run_async(_run_embed_book(book_id))
    except Exception as exc:
        logger.exception(f"embed_book failed for book {book_id}")
        if "429" in str(exc):
            countdown = 60 * (2**self.request.retries)
        else:
            countdown = 30 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


async def _upsert_chunk_avg_embedding(db, bid: uuid.UUID, model: str) -> None:
    """Compute AVG(embedding) over a book's chunks and upsert into book_embeddings.

    Only inserts/updates if the existing row is NOT source='summary'
    (summary embeddings are higher quality and should not be overwritten).
    """
    from pgvector.sqlalchemy import Vector as VectorType
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.book_embedding import BookEmbeddingChunk
    from app.models.book_embedding_unified import BookEmbedding

    avg_result = await db.execute(
        select(
            func.avg(BookEmbeddingChunk.embedding)
            .cast(VectorType(1024))
            .label("avg_emb"),
            func.count().label("cnt"),
        ).where(BookEmbeddingChunk.book_id == bid)
    )
    row = avg_result.one()
    if not row.cnt or row.cnt == 0:
        return

    stmt = pg_insert(BookEmbedding).values(
        book_id=bid,
        embedding=row.avg_emb,
        embedding_model=model,
        source_summary_count=row.cnt,
        source="chunk_avg",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["book_id"],
        set_={
            "embedding": stmt.excluded.embedding,
            "embedding_model": stmt.excluded.embedding_model,
            "source_summary_count": stmt.excluded.source_summary_count,
            "source": stmt.excluded.source,
            "updated_at": func.now(),
        },
        where=BookEmbedding.source != "summary",
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(f"Upserted chunk-avg embedding for book {bid} ({row.cnt} chunks)")


# Max token input for Qwen3-Embedding (context_length=4096)
_EMBED_TOKEN_LIMIT = 4096
# Conservative char fallback for CJK (1 CJK char ≈ 1-2 tokens)
_CHAR_FALLBACK_LIMIT = 6000


def _build_summary_text(chunks: list) -> tuple[str, int]:
    """Concatenate filtered chapter summaries for embedding.

    Returns (concatenated_text, valid_summary_count).
    Filters out noise: short summaries (<50 chars) and verbatim passthroughs
    (where summary == text.strip()[:200]).
    """
    valid_summaries: list[str] = []
    for chunk in chunks:
        summary = chunk.summary
        if not summary or len(summary) < 50:
            continue
        # Skip verbatim passthroughs — the ingestion pipeline stores
        # stripped[:200] as "summary" for sections shorter than 1000 chars
        if summary == chunk.text.strip()[:200]:
            continue
        valid_summaries.append(summary)

    if not valid_summaries:
        return "", 0

    return "\n".join(valid_summaries), len(valid_summaries)


async def _run_embed_book_summary(book_id: str) -> None:
    """Embed concatenated chapter summaries into a single book-level vector.

    Idempotent via upsert (ON CONFLICT DO UPDATE on book_id).
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    from app.database import create_task_engine
    from app.models.book import Book
    from app.models.book_embedding_unified import BookEmbedding
    from app.models.book_text import BookTextChunk
    from app.services.embedding import embed_text
    from app.services.settings import get_all_settings

    async with create_task_engine() as (_engine, session_factory):
        async with session_factory() as db:
            bid = uuid.UUID(book_id)

            # Skip image books
            img_result = await db.execute(
                select(Book.is_image_book).where(Book.id == bid)
            )
            if img_result.scalar_one_or_none() is True:
                logger.info(
                    f"Book {book_id} is an image book, skipping summary embedding"
                )
                return

            settings = await get_all_settings(db)
            api_url = settings.get("embedding_api_url", "")
            model = settings.get("embedding_model", "")
            api_key = settings.get("embedding_api_key", "")

            if not api_url or not model:
                logger.warning(
                    f"Embedding not configured, skipping summary embed for book {book_id}"
                )
                return

            # Fetch ALL chunks for this book
            all_chunks_result = await db.execute(
                select(BookTextChunk)
                .where(BookTextChunk.book_id == bid)
                .order_by(BookTextChunk.spine_index)
            )
            all_chunks = list(all_chunks_result.scalars().all())

            if not all_chunks:
                logger.info(f"Book {book_id} has no text chunks, skipping")
                return

            # Only embed when ALL chunks have summaries
            chunks_with_summary = [c for c in all_chunks if c.summary is not None]
            if len(chunks_with_summary) < len(all_chunks):
                logger.info(
                    f"Book {book_id} has {len(chunks_with_summary)}/{len(all_chunks)} chunks summarized, waiting for all"
                )
                return

            chunks = chunks_with_summary

            summary_text, valid_count = _build_summary_text(chunks)
            if not summary_text:
                logger.info(
                    f"Book {book_id} has no valid summaries after filtering, skipping"
                )
                return

            # Truncate at safe char limit for CJK text
            if len(summary_text) > _CHAR_FALLBACK_LIMIT:
                summary_text = summary_text[:_CHAR_FALLBACK_LIMIT]

            vector, usage = await embed_text(
                summary_text, api_url=api_url, model=model, api_key=api_key
            )

            # Upsert — one embedding per book, summary always wins
            stmt = insert(BookEmbedding).values(
                book_id=bid,
                embedding=vector,
                embedding_model=model,
                source_summary_count=valid_count,
                source="summary",
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["book_id"],
                set_={
                    "embedding": stmt.excluded.embedding,
                    "embedding_model": stmt.excluded.embedding_model,
                    "source_summary_count": stmt.excluded.source_summary_count,
                    "source": stmt.excluded.source,
                    "updated_at": func.now(),
                },
            )
            await db.execute(stmt)

            # Mark book as having an embedding
            from sqlalchemy import update as sa_update

            await db.execute(
                sa_update(Book).where(Book.id == bid).values(has_embedding=True)
            )
            await db.commit()

            logger.info(
                f"Embedded summary for book {book_id} ({valid_count} summaries)"
            )

            # Log usage
            from app.services.llm_usage import log_llm_usage

            await log_llm_usage(
                feature="summary_embedding",
                provider="openai_compatible",
                model=model,
                usage=usage,
                book_id=bid,
                session_factory=session_factory,
            )


@celery.task(
    name="app.tasks.embed.embed_book_summary",
    bind=True,
    max_retries=3,
    rate_limit="10/m",
)
def embed_book_summary(self, book_id: str) -> None:
    """Celery wrapper for _run_embed_book_summary."""
    try:
        from app.celeryapp import run_async

        run_async(_run_embed_book_summary(book_id))
    except Exception as exc:
        logger.exception(f"embed_book_summary failed for book {book_id}")
        if "429" in str(exc):
            countdown = 60 * (2**self.request.retries)
        else:
            countdown = 30 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)
