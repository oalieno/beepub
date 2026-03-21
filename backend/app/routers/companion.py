"""AI Reading Companion endpoints."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal, get_db
from app.deps import get_current_user
from app.models.book import Book
from app.models.companion import CompanionConversation, CompanionMessage
from app.models.user import User
from app.schemas.companion import (
    CompanionConversationOut,
    CompanionMessageRequest,
)
from app.services.companion import (
    get_or_create_conversation,
    stream_companion_response,
)
from app.services.sse import sse_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["companion"])


async def _streaming_generator(
    token_stream: AsyncIterator[str],
    conversation_id: uuid.UUID,
    user_message_id: uuid.UUID,
) -> AsyncIterator[str]:
    """Wrap the LLM token stream with SSE events and save the assistant message."""
    accumulated = []
    assistant_msg_id = uuid.uuid4()
    try:
        async for chunk in token_stream:
            accumulated.append(chunk)
            yield sse_event("token", {"text": chunk})

        full_response = "".join(accumulated)

        # Save assistant message using a dedicated DB session
        try:
            async with AsyncSessionLocal() as db:
                msg = CompanionMessage(
                    id=assistant_msg_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_response,
                )
                db.add(msg)
                await db.commit()
        except Exception:
            logger.error(
                "Failed to save assistant message for conversation %s",
                conversation_id,
                exc_info=True,
            )

        yield sse_event(
            "done",
            {
                "conversation_id": str(conversation_id),
                "message_id": str(assistant_msg_id),
            },
        )
    except Exception as exc:
        logger.error("Companion streaming error: %s", exc, exc_info=True)
        yield sse_event("error", {"message": str(exc)})


@router.post("/{book_id}/companion")
async def send_companion_message(
    book_id: uuid.UUID,
    body: CompanionMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Send a message to the AI reading companion and stream the response."""
    # Verify book exists
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )

    # Get or create conversation
    conversation = await get_or_create_conversation(db, book_id, current_user.id)

    # Start streaming
    token_stream, conv_id, user_msg_id = await stream_companion_response(
        db=db,
        book=book,
        conversation=conversation,
        user_message=body.message,
        selected_text=body.selected_text,
        cfi_range=body.cfi_range,
        current_cfi=body.current_cfi,
        user_id=current_user.id,
    )

    return StreamingResponse(
        _streaming_generator(token_stream, conv_id, user_msg_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{book_id}/companion")
async def get_companion_conversation(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanionConversationOut | None:
    """Get the existing companion conversation for a book."""
    result = await db.execute(
        select(CompanionConversation)
        .where(
            CompanionConversation.book_id == book_id,
            CompanionConversation.user_id == current_user.id,
        )
        .options(selectinload(CompanionConversation.messages))
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        return None
    return CompanionConversationOut.model_validate(conversation)


@router.delete("/{book_id}/companion", status_code=status.HTTP_204_NO_CONTENT)
async def delete_companion_conversation(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Reset/clear the companion conversation for a book."""
    result = await db.execute(
        select(CompanionConversation).where(
            CompanionConversation.book_id == book_id,
            CompanionConversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        await db.delete(conversation)
        await db.commit()
