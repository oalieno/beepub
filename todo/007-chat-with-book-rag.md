# 007 — Chat With Book (RAG)

> **Status: PARTIALLY COVERED by AI Reading Companion Sidebar**
> The in-reader chat sidebar (persistent conversations, contextual Q&A) is covered by the companion sidebar feature. The RAG pipeline (embeddings, pgvector, citations) and library-wide cross-book chat remain as future enhancements. See design doc at `~/.gstack/projects/beepub/oalieno-main-design-20260320-160000.md`.

## Goal

Add a persistent chat sidebar in the reader where users can ask any question about the book's content. AI answers with citations pointing to specific locations. Also support library-wide RAG for cross-book queries like "which of my books discusses X?"

## User Story

- As a reader, I want to ask questions about the book I'm reading and get accurate answers with references to specific passages.
- As a library user, I want to search across all my books for specific topics or quotes.

## Technical Approach

### Text Chunking & Embedding

**On book upload** (or triggered manually), process the epub into searchable chunks:

1. Extract full text using `extract_full_text()` (ticket 002)
2. Split into chunks of ~500-1000 tokens with overlap, preserving section boundaries
3. Store in `book_chunks` table with CFI location metadata
4. Generate embeddings using Gemini's text embedding API (`text-embedding-004`) or a local model

**New DB table + pgvector**:
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE book_chunks (
    id UUID PRIMARY KEY,
    book_id UUID REFERENCES books(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    spine_index INT NOT NULL,
    section_title VARCHAR(500),
    text TEXT NOT NULL,
    cfi_start VARCHAR(2000),
    embedding vector(768),  -- dimension depends on model
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON book_chunks USING ivfflat (embedding vector_cosine_ops);
```

### Book-Level Chat

**Endpoint**: `POST /api/books/{book_id}/chat`

```python
{
    "message": str,
    "conversation_id": str | None,  # for continuing a conversation
    "spoiler_free": bool  # limit retrieval to chunks before reading position
}
```

**RAG pipeline**:
1. Embed the user's question
2. Retrieve top-K (5-10) most similar chunks from the book (optionally filtered by spine_index <= current position for spoiler-free mode)
3. Construct prompt with retrieved chunks as context
4. Generate answer with instructions to cite sources: "Reference passages using [Section: Title, Page ~N] format"
5. Return answer via SSE stream + chunk references with CFI links

### Library-Wide Chat

**Endpoint**: `POST /api/chat`

```python
{
    "message": str,
    "conversation_id": str | None
}
```

Searches across all books the user has access to. Returns answers with book title + section references. Useful for: "Which of my books talks about the Meiji Restoration?" or "Find quotes about loneliness across my library."

### Conversation Persistence

**New DB table**:
```sql
CREATE TABLE ai_conversations (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    book_id UUID REFERENCES books(id) ON DELETE SET NULL,  -- null for library-wide
    title VARCHAR(200),  -- auto-generated from first message
    messages JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### Frontend

**ChatSidebar.svelte** in the reader:
- Message list with AI responses containing clickable CFI links
- Input field with send button
- Conversation history selector
- "Spoiler-free" toggle

**Library chat page** (`/chat`):
- Full-page chat interface for library-wide queries
- Results show book covers + passage references

### Embedding Infrastructure

Options (decide during implementation):
1. **Gemini Embeddings API** (`text-embedding-004`): Simple, no extra infra. ~768 dimensions.
2. **Local sentence-transformers**: Add a small Python service (`all-MiniLM-L6-v2`, ~384 dimensions). Better for privacy, runs on CPU.

Recommend starting with Gemini embeddings for simplicity, with the LLM abstraction (ticket 001) making it swappable later.

### Indexing Strategy

- Index books on upload (background task via Redis queue)
- Re-index on metadata change or manual trigger
- Show indexing status on book detail page
- Skip already-indexed books (hash file content to detect changes)

## Key Files

- `backend/app/services/epub_text.py` — text extraction (ticket 002)
- `backend/app/services/llm.py` — LLM provider (ticket 001)
- `backend/app/services/embeddings.py` — new embedding service
- `backend/app/services/rag.py` — new RAG pipeline (retrieve + generate)
- `backend/app/models/chunk.py` — BookChunk model
- `backend/app/models/conversation.py` — AiConversation model
- `backend/app/routers/chat.py` — new chat router
- `frontend/src/lib/components/reader/ChatSidebar.svelte` — new component
- `frontend/src/routes/chat/+page.svelte` — library-wide chat page
- Alembic migration for pgvector extension + new tables

## Dependencies

- Ticket 001 (LLM provider abstraction)
- Ticket 002 (epub text extraction)
- PostgreSQL `pgvector` extension (add to docker-compose postgres init)

## Verification

- Upload a book → chunks created and embedded in background
- Ask a question about a specific character → get answer with passage citations
- Click a citation → reader navigates to that passage
- Enable spoiler-free → answers only reference content before reading position
- Library-wide: ask about a topic → get results from multiple books
- Conversation persistence: close and reopen chat → history preserved
