# 003 — "Explain This" & Translate for Selected Text

> **Status: SUPERSEDED by AI Reading Companion Sidebar**
> This ticket's scope (explain, translate, follow-up chat) is fully covered by the companion sidebar feature. See design doc at `~/.gstack/projects/beepub/oalieno-main-design-20260320-160000.md`.

## Goal

Add "Explain" and "Translate" buttons to the reader's highlight menu. Users select text and get contextual AI explanations (vocabulary, historical background, literary analysis) or instant translation. Supports follow-up questions in an ephemeral chat.

## User Story

- As a reader of a foreign-language book, I want to select a passage and get a translation so I can understand it without leaving the reader.
- As a reader encountering a technical term or historical reference, I want to ask AI to explain it in the context of the book I'm reading.

## Technical Approach

### Backend

**New endpoint**: `POST /api/books/{book_id}/ask`

```python
# Request body
{
    "text": str,           # selected text
    "cfi_range": str,      # epub position
    "mode": "explain" | "translate",
    "question": str | None, # optional follow-up question
    "target_language": str | None,  # for translate mode, e.g. "zh-TW", "en"
    "history": [{"role": "user"|"assistant", "content": str}]  # ephemeral chat history
}
```

**Prompt construction**:
- System prompt includes book `display_title`, `display_authors`, `epub_language`
- For "explain": "You are a literary assistant. Explain the following passage from {title} by {authors}. Cover vocabulary, historical context, and literary significance as relevant. Respond in the same language as the passage unless asked otherwise."
- For "translate": "Translate the following passage to {target_language}. Preserve literary style and tone."
- Follow-up questions append to chat history

**Response**: SSE stream using the LLM provider abstraction (ticket 001). If 001 isn't done yet, start with synchronous JSON response and migrate to SSE later.

### Frontend

**HighlightMenu.svelte changes**:
- Add `BookOpen` (explain) and `Languages` (translate) icons from lucide-svelte
- New callbacks: `onexplain` and `ontranslate`

**New component**: `AiPanel.svelte` (slide-up panel or sidebar)
- Shows streaming AI response
- Input field for follow-up questions
- Maintains ephemeral conversation history (local state, no DB persistence)
- "Translate" mode auto-detects source language, uses user's preferred target language

**EpubReader.svelte changes**:
- Wire up new highlight menu callbacks
- Pass book metadata (title, authors, language) to AiPanel

### User Preferences

Add a `preferred_language` field to user settings (or a simple localStorage preference on frontend) for the default translation target.

## Key Files

- `frontend/src/lib/components/reader/HighlightMenu.svelte` — add buttons
- `frontend/src/lib/components/reader/EpubReader.svelte` — wire up callbacks
- `frontend/src/lib/components/reader/AiPanel.svelte` — new component
- `backend/app/routers/books.py` or new `backend/app/routers/ai.py` — new endpoint
- `backend/app/services/llm.py` — LLM provider (from ticket 001)

## Dependencies

- Ticket 001 (LLM provider abstraction) — can start without it using direct Gemini calls, then refactor
- Book metadata already available via existing Book model

## Verification

- Select text in reader → tap Explain → see AI explanation stream in
- Select text → tap Translate → see translation in preferred language
- Ask a follow-up question → AI responds with context from the ongoing conversation
- Works with Chinese, English, and Japanese text
- Test with long selections (1000+ characters)
