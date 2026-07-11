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
made on an e-reader shows up in the BeePub UI.

The reverse direction is chapter-level: an exact CFI cannot be expressed
as a crengine xpointer, but the spine index can. When the web position is
newer than the device record (no kosync marker on the interaction — the
web PUT /progress rebuilds the dict, so marker presence alone orders the
two), GET serves a synthesized ``/body/DocFragment[N]/body`` position as
device "BeePub Web"; otherwise the device record is returned verbatim and
KOReader-to-KOReader sync stays byte-exact.
"""

import asyncio
import uuid
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
from app.models.reading import UserBookInteraction
from app.models.user import User
from app.routers.libraries import accessible_book_ids_select
from app.services.auth import verify_password
from app.services.credential_cache import CredentialCache
from app.services.kosync_bridge import (
    bridge_kosync_percentage,
    section_hint_from_xpointer,
)

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


async def _accessible_book_id(
    db: AsyncSession, user: User, document: str
) -> uuid.UUID | None:
    result = await db.execute(
        select(Book.id).where(
            Book.partial_md5 == document,
            Book.id.in_(accessible_book_ids_select(user)),
        )
    )
    return result.scalars().first()


async def _bridge_percentage_to_book(
    db: AsyncSession,
    user: User,
    document: str,
    percentage: float,
    device: str | None = None,
    section_index: int | None = None,
    xpointer: str | None = None,
) -> None:
    """Reflect e-reader progress in BeePub's own reading progress.

    Books the user cannot access are skipped.
    """
    book_id = await _accessible_book_id(db, user, document)
    if book_id is None:
        return
    await bridge_kosync_percentage(
        db,
        user.id,
        book_id,
        percentage,
        device=device,
        section_index=section_index,
        xpointer=xpointer,
    )


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
            db,
            current_user,
            payload.document,
            payload.percentage,
            payload.device,
            section_index=section_hint_from_xpointer(payload.progress),
            xpointer=payload.progress,
        )

    await db.commit()
    return {
        "document": payload.document,
        "timestamp": int(datetime.now(UTC).timestamp()),
    }


async def _web_position(db: AsyncSession, user: User, document: str) -> dict | None:
    """The web reading position, when it is newer than the device record.

    No timestamp comparison needed: the bridge stamps a ``kosync`` marker
    on every device push and the web PUT /progress rebuilds the dict
    without it — marker absent + web progress present means the web moved
    last. The reader computes a paragraph-level xpointer from its section
    DOM and ships it with every save; when present it is served verbatim.
    Otherwise the position degrades to the chapter start
    (``/body/DocFragment[N]/body``, crengine's 1-based spine fragment)
    with percentage carrying the fine-grained part.
    """
    book_id = await _accessible_book_id(db, user, document)
    if book_id is None:
        return None
    interaction = (
        await db.execute(
            select(UserBookInteraction).where(
                UserBookInteraction.user_id == user.id,
                UserBookInteraction.book_id == book_id,
            )
        )
    ).scalar_one_or_none()
    progress = dict(interaction.reading_progress or {}) if interaction else {}
    if "kosync" in progress:
        return None  # the device position is newer
    percentage = progress.get("percentage")
    section_index = progress.get("section_index")
    if percentage is None or section_index is None:
        return None
    try:
        timestamp = int(datetime.fromisoformat(progress["last_read_at"]).timestamp())
    except (KeyError, TypeError, ValueError):
        timestamp = int(datetime.now(UTC).timestamp())
    # Paragraph-level xpointer from the reader when available; otherwise
    # the chapter start, which every engine can at least resolve.
    xpointer = progress.get("xpointer")
    return {
        "document": document,
        "progress": xpointer or f"/body/DocFragment[{int(section_index) + 1}]/body",
        "percentage": round(float(percentage) / 100, 4),
        "device": "BeePub Web",
        "device_id": None,
        "timestamp": timestamp,
    }


@router.get("/syncs/progress/{document}")
async def kosync_get_progress(
    document: str,
    current_user: Annotated[User, Depends(get_kosync_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    web = await _web_position(db, current_user, document)
    if web is not None:
        return web

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
