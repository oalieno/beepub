"""Text chunking — split BookTextChunk text into ~500 code point sub-chunks.

Sentence-aware splitting with CJK support:
- Soft target: 500 Unicode code points
- Hard max: 600 code points
- Overlap: 100 code points
- Prefers splitting at sentence boundaries (. ! ? 。！？)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Sentence-ending punctuation (Latin + CJK)
_SENTENCE_END = re.compile(r"[.!?。！？]\s*")

SOFT_TARGET = 500
HARD_MAX = 600
OVERLAP = 100


@dataclass
class TextSubChunk:
    """A sub-chunk of a BookTextChunk with character offsets."""

    text: str
    char_offset_start: int
    char_offset_end: int
    chunk_index: int


def split_text_into_chunks(text: str) -> list[TextSubChunk]:
    """Split text into overlapping sub-chunks for embedding.

    Returns a list of TextSubChunk with character offsets relative to the
    input text. Prefers splitting at sentence boundaries within the
    soft target to hard max range.
    """
    if not text or not text.strip():
        return []

    chunks: list[TextSubChunk] = []
    start = 0
    chunk_index = 0
    text_len = len(text)

    while start < text_len:
        # Determine the end of this chunk
        remaining = text_len - start

        if remaining <= HARD_MAX:
            # Last chunk — take everything
            end = text_len
        else:
            # Try to find a sentence boundary between SOFT_TARGET and HARD_MAX
            window = text[start + SOFT_TARGET : start + HARD_MAX]
            split_pos = _find_sentence_break(window)

            if split_pos is not None:
                end = start + SOFT_TARGET + split_pos
            else:
                # No sentence boundary found — split at SOFT_TARGET
                end = start + SOFT_TARGET

        chunk_text = text[start:end]
        if chunk_text.strip():
            chunks.append(
                TextSubChunk(
                    text=chunk_text,
                    char_offset_start=start,
                    char_offset_end=end,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

        # Advance with overlap
        next_start = end - OVERLAP
        if next_start <= start:
            # Ensure forward progress
            next_start = end
        start = next_start

    return chunks


def _find_sentence_break(window: str) -> int | None:
    """Find the best sentence break position within a text window.

    Returns the character offset (relative to window start) right after
    the sentence-ending punctuation, or None if no break found.
    """
    best = None
    for m in _SENTENCE_END.finditer(window):
        best = m.end()
    return best
