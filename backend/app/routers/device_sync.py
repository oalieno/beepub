"""Reading-state sync for device-local libraries.

The iOS app can import EPUBs directly onto the device; those books have no
server identity until they are *linked* — matched to a server book by the
KOReader partial-md5 digest (the same file identity kosync uses). This
router serves that flow: a batch digest lookup so a whole local shelf links
in one round trip.

Unlike the interactive endpoints in routers/interactions.py — where the
server stamps every timestamp — sync endpoints treat the client as the
authority on when its writes happened. That contract difference is why
they live in their own module.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.user import User
from app.routers.libraries import accessible_book_ids_select

router = APIRouter(prefix="/api/books", tags=["device-sync"])


class DigestLookupRequest(BaseModel):
    digests: list[Annotated[str, Field(min_length=32, max_length=32)]] = Field(
        max_length=500
    )


class DigestMatch(BaseModel):
    id: uuid.UUID
    title: str | None


class DigestLookupResponse(BaseModel):
    matches: dict[str, DigestMatch]


@router.post("/by-digest", response_model=DigestLookupResponse)
async def lookup_books_by_digest(
    body: DigestLookupRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Resolve KOReader partial-md5 digests to accessible books.

    Digests with no accessible match are simply absent from the response.
    When several editions share a digest, the earliest-created book wins —
    an arbitrary but deterministic pick (kosync's resolver has the same
    ambiguity).
    """
    if not body.digests:
        return DigestLookupResponse(matches={})
    result = await db.execute(
        select(Book.partial_md5, Book.id, Book.title, Book.epub_title)
        .where(
            Book.partial_md5.in_(body.digests),
            Book.id.in_(accessible_book_ids_select(current_user)),
        )
        .order_by(Book.created_at.asc())
    )
    matches: dict[str, DigestMatch] = {}
    for digest, book_id, title, epub_title in result.all():
        if digest in matches:
            continue
        matches[digest] = DigestMatch(id=book_id, title=title or epub_title)
    return DigestLookupResponse(matches=matches)
