# 004 — "Story So Far" Spoiler-Free Recap

## Goal

When a user reopens a book they haven't read in a while, offer a "Previously on..." style recap of everything up to their current reading position. Strictly avoids content beyond the reading position.

## User Story

As a reader returning to a book after weeks, I want a quick recap of the plot, characters, and open threads so I can pick up where I left off without re-reading.

## Technical Approach

### Backend

**New endpoint**: `POST /api/books/{book_id}/recap`

```python
# Request body
{
    "cfi": str  # current reading position
}
```

**Implementation**:
1. Use `extract_text_up_to()` (ticket 002) to get all text before the user's position
2. **Chunked summarization** for long books (>200k chars):
   - Split into ~50k-char chunks at section boundaries
   - Summarize each chunk independently
   - Generate final unified recap from chunk summaries
3. **Prompt**: "Summarize ONLY the content provided. Do NOT include any information beyond what is given. Structure your response as:
   - **Key Events**: Major plot points in chronological order
   - **Active Characters**: Who is involved and their current situation
   - **Open Questions**: Unresolved threads the reader should remember"
4. **Caching**: Store in a new `ai_cache` table keyed by `(book_id, user_id, type='recap', content_hash)`. Invalidate when reading position advances >5%.

**New DB table**: `ai_cache`
```sql
CREATE TABLE ai_cache (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    book_id UUID REFERENCES books(id),
    cache_type VARCHAR(50),  -- 'recap', 'summary', etc.
    content_hash VARCHAR(64),  -- hash of input position/params
    result TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Frontend

**Auto-prompt**: When opening the reader, check `last_read_at` from `UserBookInteraction.reading_progress`. If >7 days ago, show a "Story So Far" card overlay with a button to generate the recap.

**Toolbar button**: Also accessible via a toolbar icon (e.g., `ScrollText` from lucide-svelte) at any time.

**RecapPanel.svelte**: Modal/drawer showing the structured recap with loading state (this may take 10-20 seconds for long books, use SSE streaming).

## Key Files

- `backend/app/services/epub_text.py` — text extraction (ticket 002)
- `backend/app/services/llm.py` — LLM provider (ticket 001)
- `backend/app/routers/ai.py` — new recap endpoint
- `backend/app/models/` — new `ai_cache` table + Alembic migration
- `frontend/src/lib/components/reader/RecapPanel.svelte` — new component
- `frontend/src/lib/components/reader/EpubReader.svelte` — auto-prompt logic + toolbar button

## Dependencies

- Ticket 001 (LLM provider abstraction)
- Ticket 002 (epub text extraction)

## Verification

- Open a book last read 10+ days ago → see "Story So Far" card
- Generate recap → verify it only covers content before reading position (no spoilers)
- Test with a long book (300+ pages) → chunked summarization works
- Test with a short book → single-pass summarization works
- Verify caching: regenerating at same position returns cached result instantly
- Toolbar button works at any time, not just on stale books
