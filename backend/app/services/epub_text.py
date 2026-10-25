"""Extract plaintext from EPUB files.

Foundation utility for word-count, summarize, explain, recap, and chat features.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from lxml import html

from app.vendor.ebooklib import epub

# Regex for CJK Unified Ideographs (common + extensions), Kana, Hangul
_CJK_RE = re.compile(
    r"[\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Extension A
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\uac00-\ud7af"  # Hangul Syllables
    r"\uf900-\ufaff]"  # CJK Compatibility Ideographs
)

# Non-CJK word boundary split (whitespace)
_WORD_SPLIT_RE = re.compile(r"\S+")


@dataclass
class TextChunk:
    spine_index: int
    section_title: str | None
    text: str
    char_offset: int  # cumulative character offset from start of book


def _html_to_text(content: bytes) -> str:
    """Strip HTML tags and return plaintext using lxml."""
    try:
        doc = html.fromstring(content)
        return doc.text_content()
    except Exception:
        # Fallback: decode and strip tags with regex
        text = content.decode("utf-8", errors="ignore")
        return re.sub(r"<[^>]+>", "", text)


def _get_spine_items(book: epub.EpubBook) -> list[tuple[int, epub.EpubItem]]:
    """Return spine items in order as (index, item) pairs."""
    items = []
    for idx, spine_entry in enumerate(book.spine):
        item_id = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        item = book.get_item_with_id(item_id)
        if item is not None:
            items.append((idx, item))
    return items


def _extract_section_title(text: str) -> str | None:
    """Try to extract a section title from the first non-empty line."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) < 200:
            return stripped
    return None


def _body_text(content: bytes) -> str:
    """The text of the document's body alone — not its <title> or <style>,
    which the whole-document text includes."""
    try:
        body = html.fromstring(content).body
    except Exception:
        return ""
    return body.text_content() if body is not None else ""


def is_picture_text(text: str) -> bool:
    """Whether a page's text says nothing: nothing is left once the
    whitespace, digits, punctuation and symbols are gone. A manga page's
    <ploc>12</ploc>, a "- 12 -" footer and a bare <img> wrapper are
    pictures; "The cat sat." and any caption are text."""
    for ch in text:
        if ch.isspace():
            continue
        category = unicodedata.category(ch)
        if category == "Nd" or category[0] in "PS":
            continue
        return False
    return True


@dataclass
class SpinePictures:
    linear: int  # linear spine items
    pictures: int  # of those, picture pages

    @property
    def is_image_book(self) -> bool:
        """At least 80% of the linear spine items are pictures: a manga
        keeps its TOC, credits and colophon as text pages."""
        return self.linear > 0 and self.pictures * 5 >= self.linear * 4


def count_picture_pages(book: epub.EpubBook) -> SpinePictures:
    """Count the linear spine items and the picture pages among them."""
    linear = pictures = 0
    for spine_entry in book.spine:
        if isinstance(spine_entry, tuple):
            item_id, flag = spine_entry[0], spine_entry[1]
        else:
            item_id, flag = spine_entry, "yes"
        if flag == "no":
            continue
        item = book.get_item_with_id(item_id)
        if item is None:
            continue
        linear += 1
        if is_picture_text(_body_text(item.get_content())):
            pictures += 1
    return SpinePictures(linear=linear, pictures=pictures)


def classify_image_book(file_path: str) -> bool:
    """Whether the EPUB is an image book: at least 80% of its linear spine
    items are picture pages. Raises when the file cannot be read."""
    book = epub.read_epub(
        file_path, options={"ignore_ncx": True, "ignore_images": True}
    )
    return count_picture_pages(book).is_image_book


@dataclass
class ExtractedText:
    chunks: list[TextChunk]
    pictures: SpinePictures


def extract_book_text(file_path: str, max_chars: int = 500_000) -> ExtractedText:
    """The book's text chunks (see extract_full_text) and its picture-page
    count, from one read of the file. The count walks the whole spine,
    past where the chunks stop."""
    book = epub.read_epub(
        file_path, options={"ignore_ncx": True, "ignore_images": True}
    )
    return ExtractedText(
        chunks=_chunks_of(book, max_chars), pictures=count_picture_pages(book)
    )


def extract_full_text(file_path: str, max_chars: int = 500_000) -> list[TextChunk]:
    """Extract all text from epub, split by spine item.

    Returns a list of TextChunk objects, each representing one spine section.
    Stops accumulating once max_chars is reached.
    """
    book = epub.read_epub(
        file_path, options={"ignore_ncx": True, "ignore_images": True}
    )
    return _chunks_of(book, max_chars)


def _chunks_of(book: epub.EpubBook, max_chars: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    total_chars = 0

    for idx, item in _get_spine_items(book):
        content = item.get_content()
        text = _html_to_text(content).strip()
        if not text:
            continue

        if total_chars + len(text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 0:
                text = text[:remaining]
            else:
                break

        chunks.append(
            TextChunk(
                spine_index=idx,
                section_title=_extract_section_title(text),
                text=text,
                char_offset=total_chars,
            )
        )
        total_chars += len(text)

        if total_chars >= max_chars:
            break

    return chunks


def extract_text_up_to(
    file_path: str, cfi: str | None, max_chars: int = 200_000
) -> str:
    """Extract text from epub up to a given CFI position.

    If cfi is None, extract all text up to max_chars.
    CFI spine index is parsed from the CFI string (e.g. /6/4 -> spine index 1).
    """
    if cfi is None:
        chunks = extract_full_text(file_path, max_chars=max_chars)
        return "\n\n".join(c.text for c in chunks)

    # Parse spine index from CFI: /6/N -> spine_index = (N/2) - 1
    spine_cutoff = None
    cfi_match = re.match(r"/(\d+)/(\d+)", cfi)
    if cfi_match:
        n = int(cfi_match.group(2))
        spine_cutoff = (n // 2) - 1

    book = epub.read_epub(
        file_path, options={"ignore_ncx": True, "ignore_images": True}
    )
    parts: list[str] = []
    total_chars = 0

    for idx, item in _get_spine_items(book):
        if spine_cutoff is not None and idx > spine_cutoff:
            break

        content = item.get_content()
        text = _html_to_text(content).strip()
        if not text:
            continue

        if total_chars + len(text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 0:
                parts.append(text[:remaining])
            break

        parts.append(text)
        total_chars += len(text)

    return "\n\n".join(parts)


def _count_words_in_text(text: str) -> int:
    """Count words in a single text string (CJK-aware)."""
    cjk_count = len(_CJK_RE.findall(text))
    non_cjk = _CJK_RE.sub("", text)
    return cjk_count + len(_WORD_SPLIT_RE.findall(non_cjk))


def count_words_from_chunks(chunks: list[TextChunk]) -> int:
    """Count words from already-extracted TextChunk objects."""
    return sum(_count_words_in_text(chunk.text) for chunk in chunks)


def count_words_from_texts(texts: list[str]) -> int:
    """Count words from a list of plain text strings."""
    return sum(_count_words_in_text(text) for text in texts)


def count_words(file_path: str) -> int | None:
    """Count words in an epub file.

    For CJK text, each CJK character counts as one word.
    For non-CJK text, whitespace-separated tokens are counted.
    Returns None if the file cannot be parsed.
    """
    try:
        book = epub.read_epub(
            file_path, options={"ignore_ncx": True, "ignore_images": True}
        )
    except Exception:
        return None

    total = 0
    for _idx, item in _get_spine_items(book):
        try:
            content = item.get_content()
            text = _html_to_text(content)
        except Exception:
            continue

        # Count CJK characters
        cjk_count = len(_CJK_RE.findall(text))

        # Remove CJK characters, then count remaining words
        non_cjk = _CJK_RE.sub("", text)
        word_count = len(_WORD_SPLIT_RE.findall(non_cjk))

        total += cjk_count + word_count

    return total
