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
from app.models.user import User
from app.schemas.user import UserOut, UserUpdateRole
from app.services.calibre import (
    _count_calibre_epubs,
    get_sync_status,
    scan_calibre_libraries,
    sync_calibre_library,
)
from app.services.settings import get_all_settings, update_settings
from app.tasks.wordcount import compute_word_count

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
async def list_users(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).order_by(User.created_at.asc()))
    return result.scalars().all()


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

    # Check if sync is already running
    sync_status = await get_sync_status(library_id)
    if sync_status and sync_status.get("status") == "running":
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
        if not base_url:
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


@router.post("/recompute-word-counts", status_code=status.HTTP_202_ACCEPTED)
async def recompute_word_counts(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Queue word-count jobs for all books that don't have one yet."""
    result = await db.execute(select(Book.id).where(Book.word_count.is_(None)))
    book_ids = result.scalars().all()
    for bid in book_ids:
        compute_word_count.delay(str(bid))
    return {"queued": len(book_ids)}
