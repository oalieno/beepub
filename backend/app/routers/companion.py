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
    CompanionConversationSummary,
    CompanionMessageRequest,
    CompanionRenameRequest,
)
from app.services.companion import (
    get_or_create_conversation,
    stream_companion_response,
)
from app.services.llm import LLMNotConfiguredError, LLMStream
from app.services.sse import sse_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["companion"])


async def _streaming_generator(
    llm_stream: LLMStream,
    conversation_id: uuid.UUID,
    user_message_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    book_id: uuid.UUID,
    provider_name: str,
    model_name: str,
) -> AsyncIterator[str]:
    """Wrap the LLM token stream with SSE events and save the assistant message."""
    accumulated = []
    assistant_msg_id = uuid.uuid4()
    try:
        async for chunk in llm_stream:
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
                f"Failed to save assistant message for conversation {conversation_id}",
                exc_info=True,
            )

        # Log LLM usage (fire-and-forget)
        try:
            from app.services.llm_usage import log_llm_usage

            await log_llm_usage(
                feature="companion",
                provider=provider_name,
                model=model_name,
                usage=llm_stream.usage,
                user_id=user_id,
                book_id=book_id,
            )
        except Exception:
            logger.warning("Failed to log companion LLM usage", exc_info=True)

        yield sse_event(
            "done",
            {
                "conversation_id": str(conversation_id),
                "message_id": str(assistant_msg_id),
            },
        )
    except Exception as exc:
        logger.error(f"Companion streaming error: {exc}", exc_info=True)
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
    conversation = await get_or_create_conversation(
        db, book_id, current_user.id, body.conversation_id
    )

    # Start streaming
    try:
        from app.services.settings import get_all_settings

        db_settings = await get_all_settings(db)
        provider_name = db_settings.get("companion_provider", "")
        model_name = db_settings.get("companion_model", "")

        llm_stream, conv_id, user_msg_id = await stream_companion_response(
            db=db,
            book=book,
            conversation=conversation,
            user_message=body.message,
            selected_text=body.selected_text,
            cfi_range=body.cfi_range,
            current_cfi=body.current_cfi,
            user_id=current_user.id,
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return StreamingResponse(
        _streaming_generator(
            llm_stream,
            conv_id,
            user_msg_id,
            user_id=current_user.id,
            book_id=book_id,
            provider_name=provider_name,
            model_name=model_name,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{book_id}/companion")
async def list_companion_conversations(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CompanionConversationSummary]:
    """List all companion conversations for a book."""
    result = await db.execute(
        select(CompanionConversation)
        .where(
            CompanionConversation.book_id == book_id,
            CompanionConversation.user_id == current_user.id,
        )
        .order_by(CompanionConversation.updated_at.desc())
    )
    conversations = result.scalars().all()
    return [CompanionConversationSummary.model_validate(c) for c in conversations]


@router.get("/{book_id}/companion/{conversation_id}")
async def get_companion_conversation(
    book_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanionConversationOut:
    """Get a specific companion conversation with messages."""
    result = await db.execute(
        select(CompanionConversation)
        .where(
            CompanionConversation.id == conversation_id,
            CompanionConversation.book_id == book_id,
            CompanionConversation.user_id == current_user.id,
        )
        .options(selectinload(CompanionConversation.messages))
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return CompanionConversationOut.model_validate(conversation)


@router.patch("/{book_id}/companion/{conversation_id}")
async def rename_companion_conversation(
    book_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: CompanionRenameRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanionConversationSummary:
    """Rename a companion conversation."""
    result = await db.execute(
        select(CompanionConversation).where(
            CompanionConversation.id == conversation_id,
            CompanionConversation.book_id == book_id,
            CompanionConversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    conversation.title = body.title
    await db.commit()
    await db.refresh(conversation)
    return CompanionConversationSummary.model_validate(conversation)


@router.delete(
    "/{book_id}/companion/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_companion_conversation(
    book_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a specific companion conversation."""
    result = await db.execute(
        select(CompanionConversation).where(
            CompanionConversation.id == conversation_id,
            CompanionConversation.book_id == book_id,
            CompanionConversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        await db.delete(conversation)
        await db.commit()
