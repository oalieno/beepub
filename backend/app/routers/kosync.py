"""KOReader progress sync — a kosync-compatible server.

Point KOReader's progress sync plugin at ``https://<host>/kosync`` with the
normal BeePub username and password. The stock client sends md5(password)
in an ``x-auth-key`` header on every request; that key is verified against
``users.kosync_key_hash`` (bcrypt of the md5), which the server derives
whenever it sees the plaintext password — register, login, password change.
Endpoints and payloads mirror koreader-sync-server.

Progress records are stored verbatim keyed by the client's document digest
(KOReader's partial MD5 of the file), so exact positions survive
KOReader-to-KOReader sync through us. When the digest matches a book we
also bridge the percentage into the book's reading progress, so progress
made on an e-reader shows up in the BeePub UI. The reverse direction (web
progress into KOReader) is not served: KOReader jumps to the ``progress``
xpointer, and we cannot express a CFI position as one.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.book import Book
from app.models.kosync import KosyncProgress
from app.models.user import User
from app.routers.libraries import accessible_book_ids_select
from app.services.auth import verify_password
from app.services.credential_cache import CredentialCache
from app.services.kosync_bridge import bridge_kosync_percentage

router = APIRouter(tags=["kosync"])

_credential_cache = CredentialCache()


async def get_kosync_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    username = request.headers.get("x-auth-user")
    key = request.headers.get("x-auth-key")
    if not username or not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    cache_key = CredentialCache.key(username, key)
    cached_id = _credential_cache.get(cache_key)
    user: User | None = None
    if cached_id is not None:
        result = await db.execute(select(User).where(User.id == cached_id))
        user = result.scalar_one_or_none()
        if user is None:
            _credential_cache.invalidate(cache_key)

    if user is None:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        # No key hash yet = the user never logged in since kosync support
        # landed; the web login derives and stores it.
        if (
            user is None
            or user.kosync_key_hash is None
            or not await asyncio.to_thread(verify_password, key, user.kosync_key_hash)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        _credential_cache.put(cache_key, user.id)

    if not user.is_active:
        _credential_cache.invalidate(cache_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


class ProgressPayload(BaseModel):
    document: str = Field(min_length=1, max_length=64)
    progress: str | None = None
    percentage: float | None = None
    device: str | None = Field(default=None, max_length=255)
    device_id: str | None = Field(default=None, max_length=255)


@router.post("/users/create")
async def kosync_register():
    # KOReader's plugin surfaces body.message on non-201 responses, and
    # some clients (Readest) auto-try register after a 401 — so this is
    # also what a user with no sync key yet ends up reading.
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "message": "Sync uses your BeePub username and password. "
            "Create the account in the BeePub web UI — and if it already "
            "exists, log in to the web UI once to enable sync."
        },
    )


@router.get("/users/auth")
async def kosync_authorize(
    current_user: Annotated[User, Depends(get_kosync_user)],
):
    return {"authorized": "OK"}


async def _bridge_percentage_to_book(
    db: AsyncSession,
    user: User,
    document: str,
    percentage: float,
    device: str | None = None,
) -> None:
    """Reflect e-reader progress in BeePub's own reading progress.

    Books the user cannot access are skipped.
    """
    result = await db.execute(
        select(Book.id).where(
            Book.partial_md5 == document,
            Book.id.in_(accessible_book_ids_select(user)),
        )
    )
    book_id = result.scalar_one_or_none()
    if book_id is None:
        return
    await bridge_kosync_percentage(db, user.id, book_id, percentage, device=device)


@router.put("/syncs/progress")
async def kosync_update_progress(
    payload: ProgressPayload,
    current_user: Annotated[User, Depends(get_kosync_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    record = (
        await db.execute(
            select(KosyncProgress).where(
                KosyncProgress.user_id == current_user.id,
                KosyncProgress.document == payload.document,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        record = KosyncProgress(user_id=current_user.id, document=payload.document)
        db.add(record)
    record.progress = payload.progress
    record.percentage = payload.percentage
    record.device = payload.device
    record.device_id = payload.device_id
    record.updated_at = datetime.now(UTC)

    if payload.percentage is not None:
        await _bridge_percentage_to_book(
            db, current_user, payload.document, payload.percentage, payload.device
        )

    await db.commit()
    return {
        "document": payload.document,
        "timestamp": int(datetime.now(UTC).timestamp()),
    }


@router.get("/syncs/progress/{document}")
async def kosync_get_progress(
    document: str,
    current_user: Annotated[User, Depends(get_kosync_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    record = (
        await db.execute(
            select(KosyncProgress).where(
                KosyncProgress.user_id == current_user.id,
                KosyncProgress.document == document,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        # The stock client checks body.percentage to decide "no progress".
        return {"document": document}
    return {
        "document": record.document,
        "progress": record.progress,
        "percentage": record.percentage,
        "device": record.device,
        "device_id": record.device_id,
        "timestamp": int(record.updated_at.timestamp()),
    }
