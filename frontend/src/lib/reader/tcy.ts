/**
 * Tate-chu-yoko for a book forced vertical: short numbers stand upright.
 *
 * A horizontal Chinese book writes its numbers in ASCII digits, which a
 * vertical layout lays on their side. A book set vertically marks such
 * runs up itself; one that is only *forced* vertical cannot, so the
 * rendered copy of each section gets the markup: every short digit run is
 * wrapped in a `<beepub-tcy>` element styled `text-combine-upright: all`.
 * (An element of our own name rather than a span: no rule of the book's
 * — `p span`, `span:first-child` — can land on it.)
 *
 * Wrapping splits a text node into text + element(text) + text, and CFIs
 * are DOM paths. Positions must not notice. Three things make the
 * wrappers invisible to everything that is stored or exchanged:
 *
 * - `tcyFilter` — the vendored epubcfi takes a node filter; SKIP makes an
 *   element transparent, its children are indexed as the parent's own and
 *   the adjacent text nodes are merged into one chunk whose character
 *   offsets run on. Every CFI ⇄ Range conversion in the reader goes
 *   through it (`cfiFromRange`, and `book.resolveCFI`, which the core
 *   binds to the filter), so a CFI is byte-identical to the one the
 *   untouched document gives, in both directions.
 * - `wholeText` — code that reads "the text node around a point" (the
 *   whitespace skip of a saved position, a highlight's quote context)
 *   sees the text node as it was before it was split.
 * - the run rule itself never wraps a run that touches a word character,
 *   so word snapping (which grows a selection within one text node) stops
 *   at the same characters either way.
 *
 * Only the rendered document is ever wrapped. The pristine documents
 * (kosync xpointers, footnotes), the search's own parses and the anchor
 * sweep's parses are untouched copies.
 */
import * as CFI from "./vendor/foliate/epubcfi.js";

export const TCY_TAG = "beepub-tcy";

/** The rule that stands a wrapped run upright (`-webkit-text-combine` is
 *  the spelling older WebKit answers to). */
export const TCY_CSS = `
${TCY_TAG} {
  -webkit-text-combine: horizontal;
  text-combine-upright: all;
}`;

const XHTML_NS = "http://www.w3.org/1999/xhtml";

/** Root attribute under which the forced writing-mode rules stand down,
 *  so a section's own writing mode can be read (see `combineShortNumbers`
 *  and the core's `writingModeCss`). */
export const OWN_LAYOUT_ATTR = "data-beepub-own-layout";

/** The text nodes one original text node was split into, in order; every
 *  piece maps to the same list. */
const pieces = new WeakMap<Node, Text[]>();

export function isTcy(node: Node | null | undefined): node is Element {
  return (
    !!node && node.nodeType === 1 && (node as Element).localName === TCY_TAG
  );
}

/** Node filter for the vendored epubcfi: wrappers are transparent. */
export function tcyFilter(node: Node): number {
  return isTcy(node) ? NodeFilter.FILTER_SKIP : NodeFilter.FILTER_ACCEPT;
}

export interface TextPoint {
  node: Node;
  offset: number;
}

/**
 * The text node around a point as the book wrote it: its whole text, the
 * point's offset in it, and `at(i)` — the point of character `i` in the
 * document as rendered (the piece that holds the character; the end of
 * the last piece for the end of the text). A text node that was never
 * split is its own whole.
 */
export function wholeText(
  node: Node,
  offset: number,
): { text: string; offset: number; at(i: number): TextPoint } {
  const list = pieces.get(node);
  if (!list) {
    return {
      text: node.nodeValue ?? "",
      offset,
      at: (i) => ({ node, offset: i }),
    };
  }
  let text = "";
  let base = 0;
  for (const piece of list) {
    if (piece === node) base = text.length;
    text += piece.nodeValue ?? "";
  }
  return {
    text,
    offset: base + offset,
    at: (i) => {
      let sum = 0;
      for (const piece of list) {
        const length = piece.nodeValue?.length ?? 0;
        if (i < sum + length) return { node: piece, offset: i - sum };
        sum += length;
      }
      const last = list[list.length - 1];
      return { node: last, offset: last.nodeValue?.length ?? 0 };
    },
  };
}

/** A boundary point whose container is a wrapper, moved into the
 *  wrapper's text (the vendored CFI code has no step for a skipped
 *  element). Null when the point needs no moving. */
function intoText(node: Node, offset: number): TextPoint | null {
  if (!isTcy(node)) return null;
  const text = node.firstChild;
  if (!text) return null;
  return {
    node: text,
    offset: offset <= 0 ? 0 : (text.nodeValue?.length ?? 0),
  };
}

/** The range with any boundary that names a wrapper element moved into
 *  the wrapper's text. The same Range when nothing needs moving. */
export function unwrapBoundaries(range: Range): Range {
  const start = intoText(range.startContainer, range.startOffset);
  const end = intoText(range.endContainer, range.endOffset);
  if (!start && !end) return range;
  const out = range.cloneRange();
  // End first: setting a start past the end would collapse the range.
  if (end) out.setEnd(end.node, end.offset);
  if (start) out.setStart(start.node, start.offset);
  return out;
}

/** The section-local CFI of a range, wrappers transparent. */
export function cfiFromRange(range: Range): string {
  return CFI.fromRange(unwrapBoundaries(range), tcyFilter);
}

/**
 * A point at the end of a piece that another piece follows, moved to the
 * start of that next piece — the same character position, named by the
 * text node that holds the character. A CFI resolves to the earlier
 * spelling, and code that asks "which character is here" (the
 * paginator's landing rect, the long-press word lookup) reads the
 * character *after* a point in the point's own node.
 */
export function forwardPoint(node: Node, offset: number): TextPoint {
  if (!pieces.has(node) || offset < (node.nodeValue?.length ?? 0))
    return { node, offset };
  const whole = wholeText(node, offset);
  return whole.at(whole.offset);
}

/** A resolved Range with its start named by the piece that holds the
 *  character it starts on (see forwardPoint). Mutates and returns it. */
export function forwardStart(range: Range): Range {
  const { startContainer, startOffset } = range;
  const point = forwardPoint(startContainer, startOffset);
  if (point.node === startContainer) return range;
  const collapsed = range.collapsed;
  range.setStart(point.node, point.offset);
  if (collapsed) range.collapse(true);
  return range;
}

/**
 * The text of a selection. `Selection.toString()` is the rendered text —
 * what a highlight has always stored, block breaks included — but WebKit
 * renders a combined run as one object and reports U+FFFC in its place.
 * A selection that comes back with one is read from the DOM instead.
 */
export function selectedText(sel: Selection | null, range: Range): string {
  const text = sel?.toString() ?? "";
  return text.includes("\uFFFC") ? range.toString() : text;
}

// ------------------------------------------------------------ the run rule

/** Text that is not prose, or that is typeset by rules of its own. */
const SKIP_TAGS = new Set([
  "rt",
  "rp",
  "script",
  "style",
  "svg",
  "math",
  "pre",
  "code",
  "kbd",
  "samp",
  "tt",
  "textarea",
  TCY_TAG,
]);

// Characters a vertical line sets sideways, a number next to which belongs
// to that sideways run: ASCII letters, digits and the underscore, Latin
// with its extensions, Greek, Cyrillic, and the fullwidth forms of the
// first two. A superset of word-snap's WORD_CHAR and the touch
// selection's isLatinWord — a wrapped run never touches a word character,
// so growing a selection to word bounds stops where it always did.
const WORD =
  "\\w\\u00C0-\\u024F\\u0370-\\u03FF\\u0400-\\u04FF\\uFF10-\\uFF19\\uFF21-\\uFF3A\\uFF41-\\uFF5A";
// Signs that make one figure of a number and what they touch: 50%, $5, #3.
const SIGN = "%‰°$€£¥#@&";
// Marks that join two halves of one figure (3.14, 12:30, 1,000, 10-12,
// 2/3, No.5) — and a single space, so "Chapter 4" stays one sideways run.
const JOIN = ".,:;/\\-–~+×*='’\\s";

const LEAVE_BEFORE = new RegExp(`(?:[${WORD}${SIGN}]|[${WORD}][${JOIN}])$`);
const LEAVE_AFTER = new RegExp(`^(?:[${WORD}${SIGN}]|[${JOIN}][${WORD}])`);
const DIGITS = /[0-9]+/g;
const MAX_RUN = 2;
/** How far the rule looks either side of a run. */
const REACH = 2;

/**
 * Whether the run `value[start, end)` is combined:
 *
 * - it is a maximal run of one or two ASCII digits;
 * - the character before and the character after are not sideways
 *   characters (WORD) or number signs (SIGN) — so not the "20" of
 *   "2024", not "A4", "5th" or "50%";
 * - it is not one half of a figure: no joining mark or single space with
 *   a WORD character on its far side, before or after — so not "3.14",
 *   "12:30", "1,000", "10-12", "No.5" or "Chapter 4".
 *
 * `before` and `after` are the text either side of the run (REACH
 * characters are enough). What remains stands alone among CJK text and
 * punctuation: 第4章, 第12夜, 10月4日, (1), a heading that is just "4".
 */
export function combines(run: string, before: string, after: string): boolean {
  if (run.length < 1 || run.length > MAX_RUN) return false;
  return !LEAVE_BEFORE.test(before) && !LEAVE_AFTER.test(after);
}

/** Up to REACH characters of inline text just outside a text node, on
 *  one side: what a reader sees next to the node's first or last
 *  character. Stops at anything that is not plain inline content. */
function outside(node: Node, dir: -1 | 1, win: Window): string {
  const inline = (el: Element) => win.getComputedStyle(el).display === "inline";
  let at: Node = node;
  for (;;) {
    let sibling = dir < 0 ? at.previousSibling : at.nextSibling;
    // Comments and processing instructions take no room.
    while (sibling && (sibling.nodeType === 8 || sibling.nodeType === 7))
      sibling = dir < 0 ? sibling.previousSibling : sibling.nextSibling;
    if (sibling) {
      let text = "";
      if (sibling.nodeType === 3 || sibling.nodeType === 4)
        text = sibling.nodeValue ?? "";
      else if (sibling.nodeType === 1 && inline(sibling as Element))
        text = sibling.textContent ?? "";
      return dir < 0 ? text.slice(-REACH) : text.slice(0, REACH);
    }
    const parent = at.parentElement;
    if (!parent || !inline(parent)) return "";
    at = parent;
  }
}

/**
 * Wrap the short digit runs of a rendered section (see `combines`).
 * `eligible` says whether the text directly inside an element may be
 * touched — the caller knows which text the forced layout turned. Text
 * inside ruby annotations, code, SVG, MathML and existing wrappers is
 * never touched. Decides every run against the untouched document, then
 * wraps. Returns the number of runs wrapped.
 */
export function combineShortNumbers(
  doc: Document,
  eligible: (parent: Element) => boolean,
): number {
  const win = doc.defaultView;
  if (!win || !doc.body) return 0;
  const walker = doc.createTreeWalker(
    doc.body,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    {
      acceptNode: (node) => {
        if (node.nodeType === 1) {
          return SKIP_TAGS.has((node as Element).localName.toLowerCase())
            ? NodeFilter.FILTER_REJECT
            : NodeFilter.FILTER_SKIP;
        }
        return /[0-9]/.test(node.nodeValue ?? "")
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_SKIP;
      },
    },
  );
  const allowed = new Map<Element, boolean>();
  const plan: { node: Text; runs: [number, number][] }[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (!parent) continue;
    let ok = allowed.get(parent);
    if (ok === undefined) {
      ok = eligible(parent);
      allowed.set(parent, ok);
    }
    if (!ok) continue;
    const value = node.nodeValue ?? "";
    const runs: [number, number][] = [];
    for (const match of value.matchAll(DIGITS)) {
      const start = match.index ?? 0;
      const end = start + match[0].length;
      if (end - start > MAX_RUN) continue;
      let before = value.slice(Math.max(0, start - REACH), start);
      if (start < REACH) before = outside(node, -1, win) + before;
      let after = value.slice(end, end + REACH);
      if (value.length - end < REACH) after += outside(node, 1, win);
      if (combines(match[0], before, after)) runs.push([start, end]);
    }
    if (runs.length) plan.push({ node: node as Text, runs });
  }

  let count = 0;
  for (const { node, runs } of plan) {
    const total = node.length;
    const list: Text[] = [];
    let rest: Text | null = node;
    let base = 0; // offset of `rest` in the original text
    for (const [start, end] of runs) {
      if (!rest) break;
      let run: Text = rest;
      if (start > base) {
        run = rest.splitText(start - base);
        list.push(rest);
      }
      rest = end < total ? run.splitText(end - start) : null;
      const wrapper = doc.createElementNS(XHTML_NS, TCY_TAG);
      run.parentNode?.insertBefore(wrapper, run);
      wrapper.appendChild(run);
      list.push(run);
      base = end;
      count++;
    }
    if (rest) list.push(rest);
    for (const piece of list) pieces.set(piece, list);
  }
  return count;
}
