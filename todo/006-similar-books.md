# 006 — Similar Books ✅ DONE

## Goal

Show "Similar Books" on each book's detail page — other books in the user's accessible libraries that share authors, publisher, language, or tags. No AI API calls needed for Phase 1.

## User Story

As a reader, when I finish a book or browse a book's detail page, I want to see similar books so I can discover my next read without searching.

## Technical Approach

### Phase 1: Algorithmic (No AI)

**New endpoint**: `GET /api/books/{book_id}/similar?limit=6`

**Scoring algorithm** (pure SQL):
```sql
-- Weighted scoring for similarity
-- 1. Author overlap (highest weight): books sharing any author
-- 2. Same publisher
-- 3. Same language
-- 4. Same library co-occurrence
-- Each signal contributes a score; sum and rank
```

Specifically:
- **Author overlap** (`epub_authors && book.epub_authors`): +5 points per shared author
- **Same publisher** (`epub_publisher = book.epub_publisher`): +2 points
- **Same language** (`epub_language = book.epub_language`): +1 point
- **Library co-occurrence** (both books in same library): +1 point per shared library
- Exclude the book itself and books the user can't access

Return top N by score, minimum score threshold to avoid irrelevant suggestions.

### Phase 2: Tag-Based (After Ticket 005)

Once tags exist, add:
- **Tag overlap**: +3 points per shared tag
- **Same genre category**: +2 points for matching genre tags specifically

This makes the biggest quality improvement since genre/topic matching is what readers actually care about.

### Frontend

**Book detail page** (`/books/[id]`): Add a "Similar Books" section below the book info. Show a horizontal scrollable row of book cover cards (reuse existing `BookCard` component). Hide the section if no similar books found.

## Key Files

- `backend/app/routers/books.py` — new endpoint
- `backend/app/models/book.py` — Book model (existing fields used for scoring)
- `frontend/src/routes/books/[id]/+page.svelte` — add similar books section
- `frontend/src/lib/api/books.ts` — new API function

## Dependencies

- Phase 1: None (uses existing book metadata)
- Phase 2: Ticket 005 (tags system)

## Verification

- Book by Author X → similar books section shows other books by Author X
- Book in Chinese → similar books are also in Chinese (language match)
- User without access to a library → those books don't appear in similar
- Book with no similar books → section is hidden (not empty)
- Phase 2: Books with shared genre tags rank higher than just language matches
