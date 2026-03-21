"""AI Reading Companion — context assembly and streaming."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.book import Book
from app.models.book_text import BookTextChunk
from app.models.companion import CompanionConversation, CompanionMessage
from app.services.epub_text import extract_text_up_to
from app.services.llm import ChatMessage, get_companion_provider
from app.services.settings import get_all_settings

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
SURROUNDING_CONTEXT_CHARS = 500  # Unicode codepoints before/after selected text

SYSTEM_PROMPT_TEMPLATE = """\
You are a reading companion — think of yourself as a friend who's reading the same book alongside the user.

BOOK INFO:
- Title: {title}
- Authors: {authors}
- Language: {language}

PERSONALITY:
- Talk like a friend, not a textbook. Use natural conversational language.
- DON'T use bullet points or numbered lists unless the user specifically asks for structured info.
- Have opinions. Say "我覺得這段超精彩" or "老實說我也覺得這裡有點拖" — not neutral summaries.
- Match the user's energy. If they're excited, get excited. If they're annoyed, commiserate.
- Keep responses concise — 2-3 sentences for simple questions, a short paragraph for deeper ones. This is a chat, not an essay.
- Use the same language the user writes in. If they write in 中文, respond in 中文.

KNOWLEDGE RULES:
- You MUST use the book text provided below as your primary source of truth for names, terms, and events.
- When referencing characters, places, or concepts, use the EXACT terms from the book text — never substitute with similar-sounding names or your own knowledge.
- If you're unsure about a book-specific term, quote the relevant passage rather than guessing.
- Never reference events, characters, or plot points beyond the user's current reading position.
- For factual questions (science, history, etc.), clearly distinguish between what the book says and what's actually true.
- I'll do my best to avoid spoilers based on where you are in the book, though I may have general knowledge about well-known works.

ANTI-PATTERNS (never do these):
- Don't start with "好的！" or "當然！" — just answer naturally.
- Don't list things unless asked. Prose > bullets.
- Don't be sycophantic. If the user's take is wrong, gently push back.
- Don't summarize what the user just said back to them.

BOOK CONTEXT:
{book_context}
"""


async def get_or_create_conversation(
    db: AsyncSession,
    book_id: uuid.UUID,
    user_id: uuid.UUID,
) -> CompanionConversation:
    """Get existing conversation or create a new one."""
    result = await db.execute(
        select(CompanionConversation)
        .where(
            CompanionConversation.book_id == book_id,
            CompanionConversation.user_id == user_id,
        )
        .options(selectinload(CompanionConversation.messages))
    )
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation

    conversation = CompanionConversation(book_id=book_id, user_id=user_id)
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation, ["messages"])
    return conversation


MAX_CURRENT_SECTION_CHARS = 12_000
MAX_SUMMARY_CHARS = 6_000
FALLBACK_RAW_CHARS = 16_000


def _parse_spine_index_from_cfi(cfi: str | None) -> int | None:
    """Parse spine index from a CFI string. /6/N -> (N/2) - 1."""
    if not cfi:
        return None
    m = re.match(r"/(\d+)/(\d+)", cfi)
    if m:
        return (int(m.group(2)) // 2) - 1
    return None


async def _build_context_from_chunks(
    db: AsyncSession, book_id: uuid.UUID, current_spine: int | None
) -> str | None:
    """Build context from DB text chunks: past summaries + current raw text.

    Returns None if no chunks exist yet (fallback to raw extraction).
    """
    result = await db.execute(
        select(BookTextChunk)
        .where(BookTextChunk.book_id == book_id)
        .order_by(BookTextChunk.spine_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        return None

    # Determine which chunk is "current"
    current_idx = current_spine if current_spine is not None else len(chunks) - 1

    parts: list[str] = []

    # Past sections: use summaries (or truncated text if no summary yet)
    summary_parts: list[str] = []
    summary_chars = 0
    for chunk in chunks:
        if chunk.spine_index >= current_idx:
            break
        if chunk.summary:
            entry = f"[Ch {chunk.spine_index}] {chunk.summary}"
        elif len(chunk.text.strip()) < 200:
            continue  # Skip very short sections (title pages, etc.)
        else:
            # No summary yet — use first 200 chars as fallback
            entry = f"[Ch {chunk.spine_index}] {chunk.text[:200]}..."
        if summary_chars + len(entry) > MAX_SUMMARY_CHARS:
            break
        summary_parts.append(entry)
        summary_chars += len(entry)

    if summary_parts:
        parts.append("PREVIOUS CHAPTERS (summaries):\n" + "\n\n".join(summary_parts))

    # Current section: raw text
    current_chunk = next((c for c in chunks if c.spine_index == current_idx), None)
    if current_chunk:
        text = current_chunk.text
        if len(text) > MAX_CURRENT_SECTION_CHARS:
            text = text[:MAX_CURRENT_SECTION_CHARS] + "\n\n[...section truncated...]"
        section_label = current_chunk.section_title or f"Section {current_idx}"
        parts.append(f"CURRENT SECTION ({section_label}):\n{text}")

    return "\n\n---\n\n".join(parts) if parts else None


async def build_system_prompt(
    db: AsyncSession,
    book: Book,
    user_id: uuid.UUID,
    current_cfi: str | None,
) -> str:
    """Assemble the system prompt with book context."""
    title = book.epub_title or "Unknown"
    authors = ", ".join(book.epub_authors or []) or "Unknown"
    language = book.epub_language or "Unknown"

    current_spine = _parse_spine_index_from_cfi(current_cfi)

    # Try chunk-based context first (summaries + current raw text)
    book_context = await _build_context_from_chunks(db, book.id, current_spine)

    # Fallback: raw text extraction (no chunks in DB yet)
    if not book_context:
        try:
            book_context = extract_text_up_to(
                book.file_path, current_cfi, max_chars=FALLBACK_RAW_CHARS
            )
        except Exception:
            logger.warning(
                "Failed to extract text from book %s", book.id, exc_info=True
            )
            book_context = "(Book text unavailable — the EPUB file could not be read.)"

        if len(book_context) > FALLBACK_RAW_CHARS:
            book_context = (
                book_context[:FALLBACK_RAW_CHARS] + "\n\n[...text truncated...]"
            )

    return SYSTEM_PROMPT_TEMPLATE.format(
        title=title,
        authors=authors,
        language=language,
        book_context=book_context,
    )


def build_chat_messages(
    conversation: CompanionConversation,
    user_message: str,
    selected_text: str | None,
) -> list[ChatMessage]:
    """Build the message list for the LLM from conversation history."""
    messages: list[ChatMessage] = []

    # Add conversation history (last N messages)
    history = conversation.messages[-MAX_HISTORY_MESSAGES:]
    for msg in history:
        messages.append(ChatMessage(role=msg.role, content=msg.content))

    # Build the user message with selected text context
    if selected_text:
        full_message = f'[Selected text: "{selected_text}"]\n\n{user_message}'
    else:
        full_message = user_message

    messages.append(ChatMessage(role="user", content=full_message))
    return messages


async def stream_companion_response(
    db: AsyncSession,
    book: Book,
    conversation: CompanionConversation,
    user_message: str,
    selected_text: str | None,
    cfi_range: str | None,
    current_cfi: str | None,
    user_id: uuid.UUID,
) -> tuple[AsyncIterator[str], uuid.UUID, uuid.UUID]:
    """
    Save the user message, build context, and return an SSE token stream.

    Returns (token_stream, conversation_id, user_message_id).
    The caller is responsible for saving the assistant message after streaming.
    """
    # Save user message
    user_msg = CompanionMessage(
        conversation_id=conversation.id,
        role="user",
        content=user_message,
        selected_text=selected_text,
        cfi_range=cfi_range,
    )
    db.add(user_msg)
    await db.commit()

    # Build system prompt
    system_prompt = await build_system_prompt(db, book, user_id, current_cfi)

    # Build chat messages
    chat_messages = build_chat_messages(conversation, user_message, selected_text)

    # Debug: print what we're sending to the LLM
    print("=== COMPANION LLM INPUT ===")
    print(f"System prompt ({len(system_prompt)} chars):")
    print(system_prompt)
    for i, msg in enumerate(chat_messages):
        print(f"Message[{i}] role={msg.role} ({len(msg.content)} chars):")
        print(msg.content)
    print("=== END COMPANION LLM INPUT ===")

    # Stream from LLM (use DB settings)
    db_settings = await get_all_settings(db)
    provider = get_companion_provider(db_settings)
    token_stream = provider.chat_stream(chat_messages, system=system_prompt)

    return token_stream, conversation.id, user_msg.id
