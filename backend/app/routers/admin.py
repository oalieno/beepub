import asyncio
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book
from app.models.library import Library, LibraryBook
from app.models.user import User, UserRole
from app.schemas.user import (
    AdminCreateUser,
    AdminResetPassword,
    UserOut,
    UserUpdateRole,
)
from app.services.auth import hash_password
from app.services.calibre import (
    _count_calibre_epubs,
    get_sync_status,
    scan_calibre_libraries,
    sync_calibre_library,
)
from app.services.settings import get_all_settings, update_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
async def list_users(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).order_by(User.created_at.asc()))
    return result.scalars().all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminCreateUser,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=UserRole.user,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: uuid.UUID,
    body: UserUpdateRole,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = body.role
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}/password")
async def reset_user_password(
    user_id: uuid.UUID,
    body: AdminResetPassword,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()


@router.get("/stats")
async def get_stats(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user_count = (await db.execute(select(func.count(User.id)))).scalar()
    book_count = (await db.execute(select(func.count(Book.id)))).scalar()
    library_count = (await db.execute(select(func.count(Library.id)))).scalar()
    return {
        "users": user_count,
        "books": book_count,
        "libraries": library_count,
    }


# --- Calibre integration ---


class CalibreLibraryCreate(BaseModel):
    calibre_path: str
    name: str | None = None


@router.get("/calibre/libraries")
async def list_calibre_libraries(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Scan for available Calibre libraries and show linked status."""
    available = await asyncio.to_thread(scan_calibre_libraries)

    # Get already-linked libraries
    result = await db.execute(select(Library).where(Library.calibre_path.isnot(None)))
    linked = {lib.calibre_path: lib for lib in result.scalars().all()}

    output = []
    for lib in available:
        linked_lib = linked.get(lib["path"])
        output.append(
            {
                "path": lib["path"],
                "name": lib["name"],
                "calibre_book_count": lib["book_count"],
                "linked": linked_lib is not None,
                "library_id": str(linked_lib.id) if linked_lib else None,
                "library_name": linked_lib.name if linked_lib else None,
            }
        )
    return output


@router.post("/calibre/libraries", status_code=status.HTTP_201_CREATED)
async def link_calibre_library(
    body: CalibreLibraryCreate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a BeePub library linked to a Calibre library and start initial sync."""
    # Check if already linked
    existing = await db.execute(
        select(Library).where(Library.calibre_path == body.calibre_path)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Calibre library already linked")

    # Verify path exists
    db_path = os.path.join(body.calibre_path, "metadata.db")
    if not os.path.isfile(db_path):
        raise HTTPException(status_code=400, detail="No metadata.db found at path")

    # Create library
    lib_name = body.name or os.path.basename(body.calibre_path)
    library = Library(
        name=lib_name,
        calibre_path=body.calibre_path,
        created_by=current_user.id,
    )
    db.add(library)
    await db.commit()
    await db.refresh(library)

    # Start background sync
    asyncio.create_task(
        sync_calibre_library(body.calibre_path, library.id, current_user.id)
    )

    return {
        "library_id": str(library.id),
        "name": library.name,
        "calibre_path": library.calibre_path,
        "sync_started": True,
    }


@router.post(
    "/calibre/libraries/{library_id}/sync", status_code=status.HTTP_202_ACCEPTED
)
async def trigger_calibre_sync(
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Trigger a re-sync for a linked Calibre library."""
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    if not library.calibre_path:
        raise HTTPException(status_code=400, detail="Not a Calibre library")

    # Check if sync is already running (with stale detection)
    sync_status = await get_sync_status(library_id)
    if sync_status and sync_status.get("status") == "running":
        # Treat as stale if running for more than 30 minutes
        started_at = sync_status.get("started_at")
        if started_at:
            from datetime import UTC, datetime

            try:
                started = datetime.fromisoformat(started_at)
                elapsed = (datetime.now(UTC) - started).total_seconds()
                if elapsed < 1800:  # 30 minutes
                    raise HTTPException(
                        status_code=409, detail="Sync already in progress"
                    )
                # Stale — fall through to re-trigger
            except (ValueError, TypeError):
                pass  # Bad timestamp — allow re-trigger
        else:
            # No started_at (old format) — block to be safe
            raise HTTPException(status_code=409, detail="Sync already in progress")

    asyncio.create_task(
        sync_calibre_library(library.calibre_path, library.id, current_user.id)
    )
    return {"status": "sync_started"}


@router.get("/calibre/libraries/{library_id}/status")
async def get_calibre_library_status(
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get sync status and book counts for a linked Calibre library."""
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    if not library.calibre_path:
        raise HTTPException(status_code=400, detail="Not a Calibre library")

    # Count imported books
    imported_count = (
        await db.execute(
            select(func.count())
            .select_from(LibraryBook)
            .where(LibraryBook.library_id == library_id)
        )
    ).scalar()

    # Count Calibre EPUB books (lightweight count query, not full read)
    try:
        db_path = os.path.join(library.calibre_path, "metadata.db")
        calibre_count = await asyncio.to_thread(_count_calibre_epubs, db_path)
    except Exception:
        calibre_count = None

    sync = await get_sync_status(library_id)

    return {
        "library_id": str(library.id),
        "library_name": library.name,
        "calibre_path": library.calibre_path,
        "calibre_book_count": calibre_count,
        "imported_book_count": imported_count,
        "sync": sync,
    }


# --- App Settings ---


@router.get("/settings")
async def get_settings(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await get_all_settings(db)


@router.put("/settings")
async def put_settings(
    body: dict[str, str],
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await update_settings(db, body)


# --- AI Status (accessible to all authenticated users) ---

ai_router = APIRouter(prefix="/api", tags=["ai"])


@ai_router.get("/ai/status")
async def get_ai_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return which AI features are configured and available."""
    settings = await get_all_settings(db)
    return {
        "companion": bool(
            settings.get("companion_provider") and settings.get("companion_model")
        ),
        "tag": bool(settings.get("tag_provider") and settings.get("tag_model")),
        "image": bool(settings.get("image_provider") and settings.get("image_model")),
        "embedding": bool(
            settings.get("embedding_provider") and settings.get("embedding_model")
        ),
    }


@router.get("/ai/models")
async def list_ai_models(
    provider: str,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Fetch available models from a configured AI provider."""
    settings = await get_all_settings(db)

    from app.services.llm import _resolve_credentials

    api_key, base_url = _resolve_credentials(settings, provider)

    import httpx

    models: list[dict[str, str]] = []

    if provider == "gemini":
        if not api_key:
            raise HTTPException(status_code=400, detail="Gemini API key not configured")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": api_key},
            )
            resp.raise_for_status()
            for m in resp.json().get("models", []):
                model_id = m.get("name", "").removeprefix("models/")
                if model_id:
                    models.append(
                        {"id": model_id, "name": m.get("displayName", model_id)}
                    )
    elif provider == "openai":
        if not base_url or not base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400, detail="OpenAI base URL not configured"
            )
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                model_id = m.get("id", "")
                if model_id:
                    models.append({"id": model_id, "name": model_id})
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    models.sort(key=lambda m: m["name"])
    return models


# --- LLM Usage ---


@router.get("/llm-usage")
async def get_llm_usage(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    period: str = "month",
    feature: str | None = None,
):
    """Get LLM usage statistics aggregated by feature, day, and user."""
    from datetime import UTC, datetime, timedelta

    from app.models.llm_usage import LLMUsageLog

    # Price per 1M tokens: (input_price, output_price)
    # Last updated: 2026-03
    MODEL_PRICING: dict[str, tuple[float, float]] = {
        # Gemini — https://ai.google.dev/pricing
        "gemini-2.0-flash": (0.10, 0.40),
        "gemini-2.0-flash-lite": (0.075, 0.30),
        "gemini-2.5-flash": (0.30, 2.50),
        "gemini-2.5-flash-lite": (0.10, 0.40),
        "gemini-2.5-pro": (1.25, 10.00),
        "gemini-2.5-pro-preview-05-06": (1.25, 10.00),
        "gemini-3-flash-preview": (0.50, 3.00),
        "gemini-3.1-flash-lite": (0.25, 1.50),
        "gemini-3.1-pro-preview": (2.00, 12.00),
        # Gemini embedding (free tier: $0, paid tier pricing below)
        "gemini-embedding-001": (0.15, 0.00),
        "gemini-embedding-002": (0.20, 0.00),
        # OpenAI — https://openai.com/api/pricing
        "gpt-5.4": (2.50, 15.00),
        "gpt-5.4-mini": (0.75, 4.50),
        "gpt-5.4-nano": (0.20, 1.25),
        "gpt-5.1": (1.25, 10.00),
        "gpt-5.1-codex": (1.25, 10.00),
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4.1": (2.00, 8.00),
        "gpt-4.1-mini": (0.40, 1.60),
        "gpt-4.1-nano": (0.10, 0.40),
        "o1": (15.00, 60.00),
        "o3": (2.00, 8.00),
        "o3-mini": (1.10, 4.40),
        "o4-mini": (1.10, 4.40),
        # OpenAI embedding
        "text-embedding-3-small": (0.02, 0.00),
        "text-embedding-3-large": (0.13, 0.00),
    }

    def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        prices = MODEL_PRICING.get(model)
        if not prices:
            return 0.0
        return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000

    # Determine date range
    now = datetime.now(UTC)
    if period == "day":
        since = now - timedelta(days=1)
    elif period == "week":
        since = now - timedelta(weeks=1)
    else:  # month
        since = now - timedelta(days=30)

    # Base filter
    base_filter = [LLMUsageLog.created_at >= since]
    if feature:
        base_filter.append(LLMUsageLog.feature == feature)

    # By feature
    by_feature_stmt = (
        select(
            LLMUsageLog.feature,
            LLMUsageLog.provider,
            LLMUsageLog.model,
            func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
            func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
            func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
            func.count().label("call_count"),
        )
        .where(*base_filter)
        .group_by(LLMUsageLog.feature, LLMUsageLog.provider, LLMUsageLog.model)
        .order_by(func.sum(LLMUsageLog.total_tokens).desc())
    )
    by_feature_result = await db.execute(by_feature_stmt)

    # By day
    date_trunc = func.date_trunc("day", LLMUsageLog.created_at)
    by_day_stmt = (
        select(
            date_trunc.label("day"),
            LLMUsageLog.feature,
            func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
            func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
            func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
            func.count().label("call_count"),
        )
        .where(*base_filter)
        .group_by(date_trunc, LLMUsageLog.feature)
        .order_by(date_trunc.desc())
    )
    by_day_result = await db.execute(by_day_stmt)

    # By user
    from app.models.user import User as UserModel

    by_user_stmt = (
        select(
            UserModel.id.label("user_id"),
            UserModel.username,
            func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
            func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
            func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
            func.count().label("call_count"),
        )
        .join(UserModel, LLMUsageLog.user_id == UserModel.id)
        .where(*base_filter)
        .group_by(UserModel.id, UserModel.username)
        .order_by(func.sum(LLMUsageLog.total_tokens).desc())
    )
    by_user_result = await db.execute(by_user_stmt)

    # System usage (no user_id, from background tasks)
    system_stmt = select(
        func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
        func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
        func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
        func.count().label("call_count"),
    ).where(*base_filter, LLMUsageLog.user_id.is_(None))
    system_result = await db.execute(system_stmt)
    system_row = system_result.one()

    # Totals
    totals_stmt = select(
        func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
        func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
        func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
        func.count().label("call_count"),
    ).where(*base_filter)
    totals_result = await db.execute(totals_stmt)
    totals_row = totals_result.one()

    by_feature_rows = [
        {
            "feature": row.feature,
            "provider": row.provider,
            "model": row.model,
            "input_tokens": row.input_tokens or 0,
            "output_tokens": row.output_tokens or 0,
            "total_tokens": row.total_tokens or 0,
            "call_count": row.call_count,
            "estimated_cost": estimate_cost(
                row.model, row.input_tokens or 0, row.output_tokens or 0
            ),
        }
        for row in by_feature_result.all()
    ]

    return {
        "period": period,
        "since": since.isoformat(),
        "by_feature": by_feature_rows,
        "by_user": [
            *[
                {
                    "username": row.username,
                    "input_tokens": row.input_tokens or 0,
                    "output_tokens": row.output_tokens or 0,
                    "total_tokens": row.total_tokens or 0,
                    "call_count": row.call_count,
                }
                for row in by_user_result.all()
            ],
            *(
                [
                    {
                        "username": "(system)",
                        "input_tokens": system_row.input_tokens or 0,
                        "output_tokens": system_row.output_tokens or 0,
                        "total_tokens": system_row.total_tokens or 0,
                        "call_count": system_row.call_count or 0,
                    }
                ]
                if (system_row.call_count or 0) > 0
                else []
            ),
        ],
        "by_day": [
            {
                "day": row.day.isoformat() if row.day else None,
                "feature": row.feature,
                "input_tokens": row.input_tokens or 0,
                "output_tokens": row.output_tokens or 0,
                "total_tokens": row.total_tokens or 0,
                "call_count": row.call_count,
            }
            for row in by_day_result.all()
        ],
        "totals": {
            "input_tokens": totals_row.input_tokens or 0,
            "output_tokens": totals_row.output_tokens or 0,
            "total_tokens": totals_row.total_tokens or 0,
            "call_count": totals_row.call_count or 0,
            "estimated_cost": sum(r["estimated_cost"] for r in by_feature_rows),
        },
    }


# --- Semantic Similar Books ---


@router.get("/similarity-debug")
async def get_similarity_debug(
    book_a: uuid.UUID,
    book_b: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Debug endpoint: per-signal similarity breakdown between two books."""
    from sqlalchemy import text

    query = text("""
        WITH books_info AS (
            SELECT
                id,
                COALESCE(authors, epub_authors, '{}') AS authors,
                COALESCE(publisher, epub_publisher) AS publisher,
                epub_language AS language,
                COALESCE(tags, epub_tags, '{}') AS tags
            FROM books WHERE id IN (:book_a, :book_b)
        ),
        ba AS (SELECT * FROM books_info WHERE id = :book_a),
        bb AS (SELECT * FROM books_info WHERE id = :book_b)
        SELECT
            (SELECT CARDINALITY(ba.authors & bb.authors) FROM ba, bb) AS shared_authors,
            (SELECT CARDINALITY(ba.tags & bb.tags) FROM ba, bb) AS shared_tags,
            (SELECT COUNT(*) FROM book_tags a
             JOIN book_tags b ON a.tag = b.tag
             WHERE a.book_id = :book_a AND b.book_id = :book_b) AS shared_book_tags,
            (SELECT CASE WHEN ba.publisher = bb.publisher AND ba.publisher IS NOT NULL
                    THEN 1 ELSE 0 END FROM ba, bb) AS same_publisher,
            (SELECT CASE WHEN ba.language = bb.language AND ba.language IS NOT NULL
                    THEN 1 ELSE 0 END FROM ba, bb) AS same_language,
            (SELECT COUNT(DISTINCT lb1.library_id)
             FROM library_books lb1
             JOIN library_books lb2 ON lb1.library_id = lb2.library_id
             WHERE lb1.book_id = :book_a AND lb2.book_id = :book_b) AS shared_libraries
    """)

    result = await db.execute(query, {"book_a": str(book_a), "book_b": str(book_b)})
    row = result.fetchone()

    # Semantic similarity
    semantic_query = text("""
        SELECT 1 - (a.embedding <=> b.embedding) AS cosine_similarity
        FROM book_embeddings a, book_embeddings b
        WHERE a.book_id = :book_a AND b.book_id = :book_b
    """)
    sem_result = await db.execute(
        semantic_query, {"book_a": str(book_a), "book_b": str(book_b)}
    )
    sem_row = sem_result.fetchone()

    settings = await get_all_settings(db)
    semantic_weight = float(settings.get("similar_books_semantic_weight", "10.0"))

    cosine_sim = float(sem_row[0]) if sem_row else None
    semantic_score = cosine_sim * semantic_weight if cosine_sim is not None else None

    signals = {
        "author_overlap": {"count": row[0], "score": row[0] * 5},
        "tag_overlap": {"count": row[1], "score": row[1] * 3},
        "ai_tag_overlap": {"count": row[2], "score": row[2] * 3},
        "same_publisher": {"match": bool(row[3]), "score": row[3] * 2},
        "same_language": {"match": bool(row[4]), "score": row[4] * 1},
        "library_co_occurrence": {"count": row[5], "score": row[5]},
        "semantic_similarity": {
            "cosine_similarity": cosine_sim,
            "weight": semantic_weight,
            "score": semantic_score,
        },
    }

    metadata_score = sum(
        s["score"] for k, s in signals.items() if k != "semantic_similarity"
    )
    total_score = metadata_score + (semantic_score or 0)

    return {
        "book_a": str(book_a),
        "book_b": str(book_b),
        "signals": signals,
        "metadata_score": metadata_score,
        "semantic_score": semantic_score,
        "total_score": total_score,
    }


# --- Book Reports ---


@router.get("/reports")
async def list_reports(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    resolved: bool = False,
):
    """List book reports. Defaults to unresolved only."""
    from app.models.book_report import BookReport

    query = (
        select(BookReport)
        .where(BookReport.resolved == resolved)
        .order_by(BookReport.created_at.desc())
    )
    result = await db.execute(query)
    reports = result.scalars().all()

    items = []
    for r in reports:
        item = {
            "id": r.id,
            "book_id": r.book_id,
            "reported_by": r.reported_by,
            "issue_type": r.issue_type,
            "description": r.description,
            "resolved": r.resolved,
            "resolved_by": r.resolved_by,
            "created_at": r.created_at,
            "resolved_at": r.resolved_at,
            "book_title": (r.book.title or r.book.epub_title) if r.book else None,
            "book_cover": r.book.cover_path if r.book else None,
            "reporter_name": r.reporter.username if r.reporter else None,
        }
        items.append(item)
    return items


@router.put("/reports/{report_id}/resolve")
async def resolve_report(
    report_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mark a report as resolved."""
    from datetime import UTC, datetime

    from app.models.book_report import BookReport

    result = await db.execute(select(BookReport).where(BookReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if not report.resolved:
        report.resolved = True
        report.resolved_by = current_user.id
        report.resolved_at = datetime.now(UTC)
        await db.commit()

    return {"status": "resolved"}
