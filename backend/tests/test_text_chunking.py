"""Tests for app.services.text_chunking — pure-function text splitting."""

import pytest

from app.services.text_chunking import (
    HARD_MAX,
    OVERLAP,
    SOFT_TARGET,
    TextSubChunk,
    split_text_into_chunks,
)

# ---------------------------------------------------------------------------
# Empty / whitespace inputs
# ---------------------------------------------------------------------------

class TestEmptyInputs:
    def test_empty_string(self):
        assert split_text_into_chunks("") == []

    def test_none_input(self):
        assert split_text_into_chunks(None) == []

    def test_whitespace_only(self):
        assert split_text_into_chunks("   \n\t  ") == []


# ---------------------------------------------------------------------------
# Short text (fits in a single chunk)
# ---------------------------------------------------------------------------

class TestShortText:
    def test_short_text_returns_single_chunk(self):
        text = "Hello, world!"
        result = split_text_into_chunks(text)
        assert len(result) == 1
        assert result[0].text == text
        assert result[0].char_offset_start == 0
        assert result[0].char_offset_end == len(text)
        assert result[0].chunk_index == 0

    def test_text_exactly_hard_max(self):
        """At HARD_MAX, first chunk takes all text, but overlap creates a second chunk."""
        text = "a" * HARD_MAX
        result = split_text_into_chunks(text)
        # First chunk is full text; overlap (next_start = HARD_MAX - OVERLAP) creates second
        assert len(result) == 2
        assert result[0].text == text
        assert result[0].char_offset_start == 0

    def test_text_one_under_hard_max(self):
        """Same overlap behavior at HARD_MAX - 1."""
        text = "x" * (HARD_MAX - 1)
        result = split_text_into_chunks(text)
        assert len(result) == 2
        assert result[0].char_offset_start == 0


# ---------------------------------------------------------------------------
# Basic splitting at soft target
# ---------------------------------------------------------------------------

class TestBasicSplitting:
    def test_splits_long_text_without_sentences(self):
        """Without sentence boundaries, splits at SOFT_TARGET."""
        text = "a" * 1200
        result = split_text_into_chunks(text)
        assert len(result) > 1
        # First chunk should be SOFT_TARGET long
        assert len(result[0].text) == SOFT_TARGET

    def test_chunk_indices_are_sequential(self):
        text = "b" * 1500
        result = split_text_into_chunks(text)
        for i, chunk in enumerate(result):
            assert chunk.index == i if hasattr(chunk, "index") else chunk.chunk_index == i

    def test_offsets_cover_entire_text(self):
        """Every character in the original text appears in at least one chunk."""
        text = "c" * 1300
        result = split_text_into_chunks(text)
        covered = set()
        for chunk in result:
            for pos in range(chunk.char_offset_start, chunk.char_offset_end):
                covered.add(pos)
        assert covered == set(range(len(text)))

    def test_no_chunk_exceeds_hard_max(self):
        text = "d" * 3000
        result = split_text_into_chunks(text)
        for chunk in result:
            assert len(chunk.text) <= HARD_MAX


# ---------------------------------------------------------------------------
# Sentence boundary detection
# ---------------------------------------------------------------------------

class TestSentenceBoundary:
    def _make_text_with_boundary(self, punct: str) -> str:
        """Build text with a sentence boundary in the SOFT_TARGET..HARD_MAX window."""
        # Fill up to just past SOFT_TARGET, place punctuation, then pad more
        before = "a" * (SOFT_TARGET + 20)
        after = " " + "b" * (HARD_MAX * 2)
        return before + punct + after

    @pytest.mark.parametrize("punct", [".", "!", "?", "\u3002", "\uff01", "\uff1f"])
    def test_splits_at_sentence_boundary(self, punct: str):
        text = self._make_text_with_boundary(punct)
        result = split_text_into_chunks(text)
        first_chunk = result[0].text
        # The chunk should end after the punctuation, not at SOFT_TARGET
        assert len(first_chunk) > SOFT_TARGET
        assert punct in first_chunk

    def test_prefers_last_sentence_boundary_in_window(self):
        """When multiple boundaries exist in the window, pick the last one."""
        before = "a" * SOFT_TARGET
        # Two sentences in the window
        window_text = "x" * 10 + ". " + "y" * 20 + ". " + "z" * 30
        after = "w" * HARD_MAX
        text = before + window_text + after
        result = split_text_into_chunks(text)
        first_end = result[0].char_offset_end
        # Should split after the second period (the last boundary in the window)
        second_period_pos = SOFT_TARGET + 10 + 2 + 20 + 2
        assert first_end == second_period_pos

    def test_falls_back_to_soft_target_when_no_boundary(self):
        """No sentence punctuation at all — splits at SOFT_TARGET."""
        text = "a" * 2000  # no punctuation
        result = split_text_into_chunks(text)
        assert len(result[0].text) == SOFT_TARGET


# ---------------------------------------------------------------------------
# Overlap handling
# ---------------------------------------------------------------------------

class TestOverlap:
    def test_consecutive_chunks_overlap(self):
        text = "a" * 1500
        result = split_text_into_chunks(text)
        assert len(result) >= 2
        # Second chunk should start OVERLAP characters before first chunk ends
        first_end = result[0].char_offset_end
        second_start = result[1].char_offset_start
        assert first_end - second_start == OVERLAP

    def test_overlap_text_matches(self):
        """The overlapping portion should contain identical text."""
        text = "".join(str(i % 10) for i in range(1500))
        result = split_text_into_chunks(text)
        for i in range(len(result) - 1):
            overlap_from_first = result[i].text[-(result[i].char_offset_end - result[i + 1].char_offset_start):]
            overlap_from_second = result[i + 1].text[: result[i].char_offset_end - result[i + 1].char_offset_start]
            assert overlap_from_first == overlap_from_second

    def test_forward_progress_guaranteed(self):
        """Each chunk must start after the previous one."""
        text = "e" * 3000
        result = split_text_into_chunks(text)
        for i in range(1, len(result)):
            assert result[i].char_offset_start > result[i - 1].char_offset_start


# ---------------------------------------------------------------------------
# CJK text handling
# ---------------------------------------------------------------------------

class TestCJKText:
    def test_cjk_sentence_boundary(self):
        """Chinese period (。) should be detected as a sentence boundary."""
        # Build CJK text with a sentence end in the window
        before = "\u4e00" * (SOFT_TARGET + 15)  # 一
        after = "\u4e8c" * (HARD_MAX * 2)  # 二
        text = before + "\u3002" + after
        result = split_text_into_chunks(text)
        first_chunk = result[0].text
        assert "\u3002" in first_chunk
        assert len(first_chunk) > SOFT_TARGET

    def test_cjk_exclamation_boundary(self):
        before = "\u5929" * (SOFT_TARGET + 10)
        after = "\u5730" * HARD_MAX
        text = before + "\uff01" + after
        result = split_text_into_chunks(text)
        assert "\uff01" in result[0].text

    def test_cjk_question_boundary(self):
        before = "\u5929" * (SOFT_TARGET + 10)
        after = "\u5730" * HARD_MAX
        text = before + "\uff1f" + after
        result = split_text_into_chunks(text)
        assert "\uff1f" in result[0].text

    def test_mixed_cjk_and_latin(self):
        text = ("Hello world. " + "\u4f60\u597d\u4e16\u754c\u3002") * 200
        result = split_text_into_chunks(text)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk.text) <= HARD_MAX


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_long_text_without_boundaries(self):
        text = "x" * 10000
        result = split_text_into_chunks(text)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk.text) <= HARD_MAX

    def test_single_character(self):
        result = split_text_into_chunks("a")
        assert len(result) == 1
        assert result[0].text == "a"

    def test_text_just_over_hard_max(self):
        text = "a" * (HARD_MAX + 1)
        result = split_text_into_chunks(text)
        # Splits at SOFT_TARGET, then overlap creates additional chunks
        assert len(result) == 3

    def test_all_punctuation(self):
        text = "." * 1200
        result = split_text_into_chunks(text)
        assert len(result) >= 1
        for chunk in result:
            assert len(chunk.text) <= HARD_MAX

    def test_dataclass_fields(self):
        """TextSubChunk has the expected fields."""
        chunk = TextSubChunk(text="hi", char_offset_start=0, char_offset_end=2, chunk_index=0)
        assert chunk.text == "hi"
        assert chunk.char_offset_start == 0
        assert chunk.char_offset_end == 2
        assert chunk.chunk_index == 0

    def test_boundary_at_exact_soft_target(self):
        """Sentence boundary right at position SOFT_TARGET (start of window)."""
        before = "a" * (SOFT_TARGET - 1)
        # Place period right at the boundary of the window
        text = before + ". " + "b" * HARD_MAX * 2
        result = split_text_into_chunks(text)
        # The period lands at index SOFT_TARGET-1 which is just before the window
        # so the window starts scanning from SOFT_TARGET
        assert len(result) > 1
