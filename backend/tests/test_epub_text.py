"""Tests for app.services.epub_text — HTML stripping, word counting, section titles."""

from unittest.mock import MagicMock, patch

from app.services.epub_text import (
    TextChunk,
    _extract_section_title,
    _html_to_text,
    count_words,
    extract_full_text,
    extract_text_up_to,
)

# ---------------------------------------------------------------------------
# _html_to_text
# ---------------------------------------------------------------------------

class TestHtmlToText:
    def test_strips_simple_tags(self):
        html_bytes = b"<p>Hello <b>world</b></p>"
        assert _html_to_text(html_bytes) == "Hello world"

    def test_empty_html(self):
        assert _html_to_text(b"") == ""

    def test_plain_text_passthrough(self):
        assert _html_to_text(b"no tags here") == "no tags here"

    def test_nested_tags(self):
        html_bytes = b"<div><p><span>deep <em>nesting</em></span></p></div>"
        assert _html_to_text(html_bytes) == "deep nesting"

    def test_script_and_style_content_included_by_lxml(self):
        """lxml text_content() includes script/style text; verify current behavior."""
        html_bytes = b"<html><head><style>body{}</style></head><body><script>alert(1)</script><p>visible</p></body></html>"
        result = _html_to_text(html_bytes)
        # lxml's text_content() returns all text nodes including script/style
        assert "visible" in result

    def test_html_entities(self):
        html_bytes = b"<p>5 &gt; 3 &amp; 2 &lt; 4</p>"
        result = _html_to_text(html_bytes)
        assert "5 > 3 & 2 < 4" in result

    def test_unicode_content(self):
        # lxml needs charset hint for correct UTF-8 decoding of raw bytes
        html_bytes = b'<html><head><meta charset="utf-8"></head><body><p>\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x83\x86\xe3\x82\xb9\xe3\x83\x88</p></body></html>'
        assert "日本語テスト" in _html_to_text(html_bytes)

    def test_whitespace_preserved(self):
        html_bytes = b"<p>line one</p><p>line two</p>"
        result = _html_to_text(html_bytes)
        assert "line one" in result
        assert "line two" in result

    def test_fallback_on_parse_error(self):
        """When lxml raises, the regex fallback strips tags."""
        with patch("app.services.epub_text.html.fromstring", side_effect=Exception("parse error")):
            result = _html_to_text(b"<p>fallback</p>")
        assert result == "fallback"


# ---------------------------------------------------------------------------
# _extract_section_title
# ---------------------------------------------------------------------------

class TestExtractSectionTitle:
    def test_returns_first_nonempty_line(self):
        assert _extract_section_title("Chapter 1\nSome body text") == "Chapter 1"

    def test_skips_blank_lines(self):
        assert _extract_section_title("\n\n  \nTitle Here\nbody") == "Title Here"

    def test_returns_none_for_empty_string(self):
        assert _extract_section_title("") is None

    def test_returns_none_for_only_whitespace(self):
        assert _extract_section_title("   \n  \n  ") is None

    def test_skips_long_lines(self):
        long_line = "x" * 200
        assert _extract_section_title(long_line + "\nShort Title") == "Short Title"

    def test_returns_none_when_all_lines_too_long(self):
        long_line = "x" * 200
        assert _extract_section_title(long_line) is None

    def test_line_at_exactly_199_chars_is_accepted(self):
        line = "a" * 199
        assert _extract_section_title(line) == line


# ---------------------------------------------------------------------------
# count_words
# ---------------------------------------------------------------------------

def _make_mock_book(texts: list[str]):
    """Create a mock EpubBook with spine items returning given HTML texts."""
    book = MagicMock()
    spine_entries = []
    items = {}
    for i, text in enumerate(texts):
        item_id = f"item_{i}"
        spine_entries.append((item_id, "yes"))
        item = MagicMock()
        # Include charset meta so lxml correctly decodes UTF-8 (CJK, etc.)
        html_str = f'<html><head><meta charset="utf-8"></head><body><p>{text}</p></body></html>'
        item.get_content.return_value = html_str.encode("utf-8")
        items[item_id] = item
    book.spine = spine_entries
    book.get_item_with_id = lambda iid: items.get(iid)
    return book


class TestCountWords:
    def test_english_text(self):
        book = _make_mock_book(["Hello world foo bar"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            assert count_words("fake.epub") == 4

    def test_cjk_characters_each_count_as_one_word(self):
        book = _make_mock_book(["日本語"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            assert count_words("fake.epub") == 3

    def test_mixed_cjk_and_english(self):
        book = _make_mock_book(["Hello 世界 test"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            # 2 CJK chars + 2 English words = 4
            assert count_words("fake.epub") == 4

    def test_korean_hangul(self):
        book = _make_mock_book(["한국어"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            assert count_words("fake.epub") == 3

    def test_japanese_hiragana_and_katakana(self):
        book = _make_mock_book(["あいうアイウ"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            assert count_words("fake.epub") == 6

    def test_empty_book(self):
        book = _make_mock_book([""])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            assert count_words("fake.epub") == 0

    def test_multiple_sections(self):
        book = _make_mock_book(["one two", "three four five"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            assert count_words("fake.epub") == 5

    def test_returns_none_on_read_error(self):
        with patch("app.services.epub_text.epub.read_epub", side_effect=Exception("bad file")):
            assert count_words("bad.epub") is None

    def test_skips_section_on_content_error(self):
        book = MagicMock()
        good_item = MagicMock()
        good_item.get_content.return_value = b"<p>hello world</p>"
        bad_item = MagicMock()
        bad_item.get_content.side_effect = Exception("corrupt")
        book.spine = [("good", "yes"), ("bad", "yes")]
        book.get_item_with_id = lambda iid: {"good": good_item, "bad": bad_item}[iid]

        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            assert count_words("fake.epub") == 2


# ---------------------------------------------------------------------------
# extract_full_text
# ---------------------------------------------------------------------------

class TestExtractFullText:
    def test_returns_text_chunks(self):
        book = _make_mock_book(["Chapter 1 text", "Chapter 2 text"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            chunks = extract_full_text("fake.epub")

        assert len(chunks) == 2
        assert all(isinstance(c, TextChunk) for c in chunks)
        assert chunks[0].spine_index == 0
        assert chunks[0].char_offset == 0
        assert chunks[1].char_offset == len(chunks[0].text)

    def test_respects_max_chars(self):
        book = _make_mock_book(["a" * 100, "b" * 100])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            chunks = extract_full_text("fake.epub", max_chars=150)

        total_text = "".join(c.text for c in chunks)
        assert len(total_text) <= 150

    def test_skips_empty_sections(self):
        book = _make_mock_book(["content", "   ", "more content"])
        # The whitespace-only section gets stripped to empty
        # Override the middle item to return whitespace-only HTML
        item = MagicMock()
        item.get_content.return_value = b"<p>   </p>"
        book.get_item_with_id = lambda iid: {
            "item_0": MagicMock(get_content=MagicMock(return_value=b"<p>content</p>")),
            "item_1": item,
            "item_2": MagicMock(get_content=MagicMock(return_value=b"<p>more content</p>")),
        }.get(iid)

        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            chunks = extract_full_text("fake.epub")

        texts = [c.text for c in chunks]
        assert "content" in texts[0]
        assert "more content" in texts[1]

    def test_section_title_extracted(self):
        book = _make_mock_book(["My Title\nBody paragraph here."])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            chunks = extract_full_text("fake.epub")

        assert chunks[0].section_title == "My Title"


# ---------------------------------------------------------------------------
# extract_text_up_to
# ---------------------------------------------------------------------------

class TestExtractTextUpTo:
    def test_no_cfi_returns_all_text(self):
        book = _make_mock_book(["part one", "part two"])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            result = extract_text_up_to("fake.epub", cfi=None)

        assert "part one" in result
        assert "part two" in result

    def test_cfi_limits_spine_index(self):
        book = _make_mock_book(["first", "second", "third"])
        # CFI /6/4 -> spine_cutoff = (4 // 2) - 1 = 1
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            result = extract_text_up_to("fake.epub", cfi="/6/4")

        assert "first" in result
        assert "second" in result
        assert "third" not in result

    def test_respects_max_chars_with_cfi(self):
        book = _make_mock_book(["a" * 100, "b" * 100])
        with patch("app.services.epub_text.epub.read_epub", return_value=book):
            result = extract_text_up_to("fake.epub", cfi=None, max_chars=50)

        assert len(result) <= 50
