# 002 — Epub Text Extraction Utility ✅ DONE

## Goal

Create a shared utility to extract plaintext from epub files, optionally up to a given reading position. This is the foundation for explain, summarize, recap, and chat features.

## User Story

As a developer, I need a reliable way to extract readable text from an epub file (with optional position cutoff) so that AI features can use book content as context.

## Technical Approach

### New Service: `backend/app/services/epub_text.py`

```python
def extract_full_text(file_path: str, max_chars: int = 500_000) -> list[TextChunk]:
    """Extract all text from epub, split by spine item."""
    ...

def extract_text_up_to(file_path: str, cfi: str | None, max_chars: int = 200_000) -> str:
    """Extract text from epub up to a given CFI position. If cfi is None, extract all."""
    ...

@dataclass
class TextChunk:
    spine_index: int
    section_title: str | None
    text: str
    char_offset: int  # cumulative character offset from start of book
```

### Implementation Details

1. **Open epub** with `ebooklib.epub.read_epub(file_path, options={"ignore_ncx": True})` (same pattern as `epub_parser.py`)
2. **Iterate spine items** in order, get HTML content, strip tags with BeautifulSoup or a lightweight regex-based approach
3. **CFI position mapping**: epub.js CFIs encode spine item index (e.g., `/6/4` = spine index 2). Parse the spine index from CFI to know which section to stop at. For within-section cutoff, use a rough character-based estimate (good enough for AI context).
4. **Return structured chunks** for features that need per-section access (chat RAG), or concatenated text for features that need a single string (summarize, recap).
5. **Handle edge cases**: encrypted epubs (skip gracefully), missing spine items, non-UTF8 content.

### Dependencies to Add

- `beautifulsoup4` is already a dependency in metadata-daemon but may need adding to backend's `pyproject.toml` (or use a lightweight regex strip — check if bs4 is already available in backend)

## Key Files

- `backend/app/services/epub_parser.py` — existing epub handling (reference for patterns)
- `backend/app/services/epub_text.py` — new file
- `backend/app/vendor/ebooklib/` — vendored ebooklib

## Dependencies

None. This is a foundation ticket.

## Verification

- Extract text from a test epub, verify output is clean plaintext (no HTML tags)
- Extract with CFI cutoff, verify it stops at the right spine section
- Test with CJK (Chinese/Japanese) content since BeePub handles many Chinese books
- Test with a large epub (500+ pages) — verify `max_chars` truncation works
