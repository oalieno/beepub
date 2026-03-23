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


@celery.task(
    name="app.tasks.embed.embed_book",
    bind=True,
    max_retries=5,
    rate_limit="10/m",
)
def embed_book(self, book_id: str) -> None:
    """Embed all text chunks of a book into BookEmbeddingChunk rows.

    Idempotent at chunk level — skips sub-chunks that already have embeddings.
    """

    async def _run() -> None:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert

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
            api_url = settings.get("embedding_api_url", "")
            model = settings.get("embedding_model", "")
            api_key = settings.get("embedding_api_key", "")

            if not api_url or not model:
                logger.warning(
                    "Embedding not configured (api_url=%s, model=%s), skipping book %s",
                    api_url,
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

            logger.info("Embedded %d sub-chunks for book %s", total_embedded, book_id)

    try:
        from app.celeryapp import run_async

        run_async(_run())
    except Exception as exc:
        logger.exception("embed_book failed for book %s", book_id)
        # Longer backoff for rate limits (429)
        if "429" in str(exc):
            countdown = 60 * (2**self.request.retries)
        else:
            countdown = 30 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


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


@celery.task(
    name="app.tasks.embed.embed_book_summary",
    bind=True,
    max_retries=3,
    rate_limit="10/m",
)
def embed_book_summary(self, book_id: str) -> None:
    """Embed concatenated chapter summaries into a single book-level vector.

    Idempotent via upsert (ON CONFLICT DO UPDATE on book_id).
    Called at the end of summarize_chunks — re-embeds on each invocation.
    """

    async def _run() -> None:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert

        from app.database import create_task_session
        from app.models.book_summary_embedding import BookSummaryEmbedding
        from app.models.book_text import BookTextChunk
        from app.services.embedding import embed_text
        from app.services.settings import get_all_settings

        session_factory = create_task_session()
        async with session_factory() as db:
            bid = uuid.UUID(book_id)

            settings = await get_all_settings(db)
            api_url = settings.get("embedding_api_url", "")
            model = settings.get("embedding_model", "")
            api_key = settings.get("embedding_api_key", "")

            if not api_url or not model:
                logger.warning(
                    "Embedding not configured, skipping summary embed for book %s",
                    book_id,
                )
                return

            # Fetch all chunks with summaries, ordered by spine_index
            result = await db.execute(
                select(BookTextChunk)
                .where(
                    BookTextChunk.book_id == bid,
                    BookTextChunk.summary.isnot(None),
                )
                .order_by(BookTextChunk.spine_index)
            )
            chunks = list(result.scalars().all())

            if not chunks:
                logger.info("Book %s has no summarized chunks, skipping", book_id)
                return

            summary_text, valid_count = _build_summary_text(chunks)
            if not summary_text:
                logger.info(
                    "Book %s has no valid summaries after filtering, skipping", book_id
                )
                return

            # Truncate at safe char limit for CJK text
            if len(summary_text) > _CHAR_FALLBACK_LIMIT:
                summary_text = summary_text[:_CHAR_FALLBACK_LIMIT]

            vector, usage = await embed_text(
                summary_text, api_url=api_url, model=model, api_key=api_key
            )

            # Upsert — one embedding per book
            stmt = insert(BookSummaryEmbedding).values(
                book_id=bid,
                embedding=vector,
                embedding_model=model,
                source_summary_count=valid_count,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["book_id"],
                set_={
                    "embedding": stmt.excluded.embedding,
                    "embedding_model": stmt.excluded.embedding_model,
                    "source_summary_count": stmt.excluded.source_summary_count,
                    "updated_at": func.now(),
                },
            )
            await db.execute(stmt)
            await db.commit()

            logger.info(
                "Embedded summary for book %s (%d summaries)", book_id, valid_count
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

    try:
        from app.celeryapp import run_async

        run_async(_run())
    except Exception as exc:
        logger.exception("embed_book_summary failed for book %s", book_id)
        if "429" in str(exc):
            countdown = 60 * (2**self.request.retries)
        else:
            countdown = 30 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


@celery.task(
    name="app.tasks.embed.backfill_summary_embeddings",
    bind=True,
)
def backfill_summary_embeddings(self) -> None:
    """Backfill summary embeddings for all books that have summaries but no embedding.

    Uses batch embedding API (up to 100 texts per call) for efficiency.
    Ordered by reading activity DESC to prioritize books users interact with.
    """

    async def _run() -> None:
        import asyncio

        from sqlalchemy import func as sa_func
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert

        from app.database import create_task_session
        from app.models.book_summary_embedding import BookSummaryEmbedding
        from app.models.book_text import BookTextChunk
        from app.models.reading import UserBookInteraction
        from app.services.embedding import embed_texts
        from app.services.job_queue import get_job_status, set_job_status
        from app.services.settings import get_all_settings

        job_type = "summary_embedding"
        current = await get_job_status(job_type)
        if current and current.get("status") == "running":
            logger.info("backfill_summary_embeddings already running, skipping")
            return
        if current and current.get("status") == "cancelled":
            logger.info("backfill_summary_embeddings was cancelled, skipping")
            return

        session_factory = create_task_session()
        async with session_factory() as db:
            settings = await get_all_settings(db)
            api_url = settings.get("embedding_api_url", "")
            model = settings.get("embedding_model", "")
            api_key = settings.get("embedding_api_key", "")

            if not api_url or not model:
                logger.warning("Embedding not configured, skipping backfill")
                await set_job_status(job_type, status="completed", total=0, processed=0)
                return

            # Find books with summaries but no BookSummaryEmbedding
            # Order by interaction count DESC (most-used books first)
            interaction_count = (
                select(
                    UserBookInteraction.book_id,
                    sa_func.count().label("cnt"),
                )
                .group_by(UserBookInteraction.book_id)
                .subquery()
            )

            books_needing_embed = (
                select(BookTextChunk.book_id)
                .where(
                    BookTextChunk.summary.isnot(None),
                    ~BookTextChunk.book_id.in_(
                        select(BookSummaryEmbedding.book_id)
                    ),
                )
                .group_by(BookTextChunk.book_id)
                .outerjoin(
                    interaction_count,
                    BookTextChunk.book_id == interaction_count.c.book_id,
                )
                .order_by(sa_func.coalesce(interaction_count.c.cnt, 0).desc())
            )

            result = await db.execute(books_needing_embed)
            book_ids = [row[0] for row in result.all()]

        total = len(book_ids)
        if total == 0:
            logger.info("backfill_summary_embeddings: nothing to do")
            await set_job_status(job_type, status="completed", total=0, processed=0)
            return

        logger.info("backfill_summary_embeddings: %d books to process", total)
        await set_job_status(job_type, status="running", total=total, processed=0)

        processed = 0
        failed = 0

        # Process in batches of 100 (max for Gemini batch API)
        for i in range(0, total, _EMBED_BATCH_SIZE):
            # Check if cancelled
            current = await get_job_status(job_type)
            if current and current.get("status") == "cancelled":
                logger.info("backfill_summary_embeddings cancelled, stopping")
                return

            batch_ids = book_ids[i : i + _EMBED_BATCH_SIZE]
            batch_texts: list[str] = []
            batch_meta: list[tuple[uuid.UUID, int]] = []  # (book_id, summary_count)

            async with session_factory() as db:
                for bid in batch_ids:
                    result = await db.execute(
                        select(BookTextChunk)
                        .where(
                            BookTextChunk.book_id == bid,
                            BookTextChunk.summary.isnot(None),
                        )
                        .order_by(BookTextChunk.spine_index)
                    )
                    chunks = list(result.scalars().all())
                    text, count = _build_summary_text(chunks)
                    if text:
                        # Truncate at safe limit for batch (skip countTokens for speed)
                        if len(text) > _CHAR_FALLBACK_LIMIT:
                            text = text[:_CHAR_FALLBACK_LIMIT]
                        batch_texts.append(text)
                        batch_meta.append((bid, count))

            if not batch_texts:
                processed += len(batch_ids)
                await set_job_status(
                    job_type, status="running", total=total, processed=processed
                )
                continue

            try:
                vectors, usage = await embed_texts(
                    batch_texts, api_url=api_url, model=model, api_key=api_key
                )

                async with session_factory() as db:
                    for (bid, count), vector in zip(batch_meta, vectors):
                        stmt = insert(BookSummaryEmbedding).values(
                            book_id=bid,
                            embedding=vector,
                            embedding_model=model,
                            source_summary_count=count,
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["book_id"],
                            set_={
                                "embedding": stmt.excluded.embedding,
                                "embedding_model": stmt.excluded.embedding_model,
                                "source_summary_count": stmt.excluded.source_summary_count,
                                "updated_at": func.now(),
                            },
                        )
                        await db.execute(stmt)
                    await db.commit()

                # Log usage
                from app.services.llm_usage import log_llm_usage

                await log_llm_usage(
                    feature="summary_embedding",
                    provider="openai_compatible",
                    model=model,
                    usage=usage,
                    session_factory=session_factory,
                )

                processed += len(batch_ids)

            except Exception:
                logger.exception(
                    "backfill_summary_embeddings batch failed at offset %d", i
                )
                failed += len(batch_ids)
                processed += len(batch_ids)

            await set_job_status(
                job_type, status="running", total=total, processed=processed
            )

            # Rate limit: pause between batches
            await asyncio.sleep(2)

        final_status = "completed" if failed == 0 else "completed_with_errors"
        await set_job_status(
            job_type, status=final_status, total=total, processed=processed
        )
        logger.info(
            "backfill_summary_embeddings done: %d processed, %d failed",
            processed - failed,
            failed,
        )

    try:
        from app.celeryapp import run_async

        run_async(_run())
    except Exception as exc:
        logger.exception("backfill_summary_embeddings failed")
        raise self.retry(exc=exc, countdown=60)


@celery.task(
    name="app.tasks.embed.build_search_index",
    bind=True,
)
def build_search_index(self, batch_size: int = 10) -> None:
    """Legacy wrapper — delegates to the unified bulk job system."""
    from app.tasks.bulk_jobs import run_bulk_job

    run_bulk_job("embedding", "missing")
