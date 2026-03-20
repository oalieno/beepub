# 005 — Tags/Genres System with AI Auto-Tagging ✅ DONE

## Goal

Add a tag/genre system to BeePub (currently none exists). AI automatically suggests tags when books are uploaded or metadata is fetched. Users can manually add/remove tags. Tags enable filtering on library pages and power the similar books feature (ticket 006).

## User Story

- As an admin, I want books to be automatically tagged by genre/mood/topic so the library is organized without manual work.
- As a reader, I want to filter library books by genre or topic to find what I'm in the mood for.
- As a user, I want to manually add or remove tags to correct AI suggestions.

## Technical Approach

### New DB Models

```sql
CREATE TABLE tags (
    id UUID PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    category VARCHAR(20) NOT NULL  -- 'genre', 'mood', 'topic', 'custom'
);

CREATE TABLE book_tags (
    book_id UUID REFERENCES books(id) ON DELETE CASCADE,
    tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
    source VARCHAR(20) NOT NULL,  -- 'ai', 'user', 'metadata'
    confidence FLOAT,  -- AI confidence score (null for manual tags)
    PRIMARY KEY (book_id, tag_id)
);
```

### Predefined Tag Vocabulary

Maintain a curated list of ~100 common tags in `backend/app/services/tags.py`:
- **Genres**: fiction, non-fiction, sci-fi, fantasy, mystery, romance, horror, thriller, literary-fiction, historical-fiction, biography, memoir, self-help, philosophy, science, technology, poetry, comics, light-novel, etc.
- **Moods**: dark, lighthearted, thought-provoking, suspenseful, romantic, melancholic, humorous, inspiring
- **Topics**: war, love, identity, family, politics, AI, space, magic, coming-of-age, etc.

Seed these via Alembic migration.

### AI Auto-Tagging Flow

1. Triggered after metadata fetch in metadata-daemon (after Goodreads/Readmoo processing)
2. Also triggered on book upload if description is available
3. **Prompt**: "Given this book's metadata, select appropriate tags from the provided vocabulary. Also suggest up to 3 custom tags not in the vocabulary if needed. Return JSON: `[{tag, category, confidence}]`"
4. Input: title, authors, description, language, reviews (from external metadata)
5. Parse response, upsert into `book_tags` with `source='ai'`

### API Endpoints

- `GET /api/tags` — list all tags (with book counts)
- `GET /api/books/{book_id}/tags` — get tags for a book
- `POST /api/books/{book_id}/tags` — add manual tag `{ name: str }`
- `DELETE /api/books/{book_id}/tags/{tag_id}` — remove tag
- `POST /api/books/{book_id}/auto-tag` — re-run AI tagging (admin)

### Library Filtering

Extend `GET /api/libraries/{library_id}/books` to accept `?tags=sci-fi,fantasy` query parameter. Filter using `book_tags` join.

### Frontend

- **Book detail page**: Tag chips below book info. Edit button for add/remove.
- **Library page**: Tag filter bar (horizontal scrollable chips or dropdown).
- **Tag management page** (admin): View all tags, merge duplicates, delete unused.

### Metadata Daemon Integration

The metadata-daemon needs access to the LLM. Options:
1. Add `GEMINI_API_KEY` to metadata-daemon's env in `docker-compose.yml` and call Gemini directly
2. Or call the backend's AI endpoint via HTTP (keeps API key in one place)

Recommend option 1 for simplicity.

## Key Files

- `backend/app/models/tag.py` — new models (Tag, BookTag)
- `backend/app/routers/tags.py` — new router
- `backend/app/routers/libraries.py` — extend with tag filtering
- `backend/app/services/tags.py` — predefined vocabulary + AI tagging logic
- `metadata-daemon/daemon/queue.py` — add auto-tagging step after metadata fetch
- `frontend/src/lib/components/TagChips.svelte` — new reusable component
- Alembic migration for new tables + seed tags

## Dependencies

- Ticket 001 (LLM provider) — or call Gemini directly as a simpler starting point

## Verification

- Upload a book → tags auto-generated from description
- Metadata fetch completes → tags added/updated
- Manual tag add/remove works
- Library page shows tag filter → filtering returns correct books
- AI returns tags from the curated vocabulary (not random strings)
- Books in multiple languages get appropriate language-aware tags
