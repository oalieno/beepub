/**
 * Kindle-style word snapping for highlight selection.
 *
 * Alphabetic scripts only — CJK has no word delimiters and readers there
 * select by character deliberately, so CJK text is left untouched. Matches
 * the isLatinWord class in ios-touch-selection.ts (Latin incl. extensions
 * + Cyrillic).
 */

const WORD_CHAR = /[\wÀ-ɏЀ-ӿ]/;

/**
 * Expand a Range outward so it never starts or ends mid-word. Only ever
 * grows the selection, only within the boundary text nodes (a word split
 * across element boundaries stays cut — rare enough to ignore), and only
 * when the cut actually lands inside a word: both characters around the
 * boundary must be word characters.
 */
export function snapRangeToWordBounds(range: Range): Range {
  const r = range.cloneRange();

  const start = r.startContainer;
  if (start.nodeType === Node.TEXT_NODE) {
    const text = start.textContent ?? "";
    let o = r.startOffset;
    if (
      o > 0 &&
      o < text.length &&
      WORD_CHAR.test(text[o]) &&
      WORD_CHAR.test(text[o - 1])
    ) {
      while (o > 0 && WORD_CHAR.test(text[o - 1])) o--;
      r.setStart(start, o);
    }
  }

  const end = r.endContainer;
  if (end.nodeType === Node.TEXT_NODE) {
    const text = end.textContent ?? "";
    let o = r.endOffset;
    if (
      o > 0 &&
      o < text.length &&
      WORD_CHAR.test(text[o - 1]) &&
      WORD_CHAR.test(text[o])
    ) {
      while (o < text.length && WORD_CHAR.test(text[o])) o++;
      r.setEnd(end, o);
    }
  }

  return r;
}
