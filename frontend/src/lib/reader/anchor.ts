/**
 * Highlight anchor verification and healing on the foliate parser.
 *
 * A stored CFI stops resolving when the book file is rewritten (calibre
 * metadata edit, re-conversion, re-split). Each anchor is checked against
 * the section DOM; the ones that moved are re-found by quote (W3C
 * TextQuoteSelector spirit: the text plus stored prefix/suffix context),
 * first in their own section, then across the spine. Anything that cannot
 * be relocated unambiguously is reported broken — a guessed anchor would
 * silently move the user's highlight, which is worse.
 *
 * Same contract as the epub.js version (components/reader/highlight-anchor)
 * so the component applies either report the same way.
 */
import * as CFI from "./vendor/foliate/epubcfi.js";
import type { Book } from "./core";
import { cfiFromRange } from "./tcy";

export interface QuoteSelector {
  text: string;
  prefix?: string | null;
  suffix?: string | null;
}

export interface AnchorInput extends QuoteSelector {
  id: string;
  cfi: string;
  sectionIndex?: number | null;
}

export interface HealedAnchor {
  id: string;
  oldCfi: string;
  cfi: string;
  sectionIndex: number;
}

export interface AnchorReport {
  healed: HealedAnchor[];
  broken: string[];
}

const normalize = (s: string) => s.replace(/[\s ]+/g, " ").trim();
const isSpace = (ch: string) => /[\s ]/.test(ch);
const CONTEXT = 20;

/**
 * Find a quote in a document (whitespace-collapsed, exact otherwise).
 * Returns a Range only when the match is unambiguous: a single occurrence,
 * or several where the stored prefix/suffix context singles one out.
 * Works on an unrendered DOM (no layout needed).
 */
export function findQuote(doc: Document, q: QuoteSelector): Range | null {
  const needle = normalize(q.text);
  const body = doc.body;
  if (!needle || !body) return null;

  // Flatten the text with whitespace runs collapsed to one space, keeping
  // a character → (node, offset) map so a match maps back to a Range.
  let text = "";
  const map: { node: Text; offset: number }[] = [];
  let lastWasSpace = true; // drops leading whitespace
  const walker = doc.createTreeWalker(body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const value = node.nodeValue ?? "";
    for (let i = 0; i < value.length; i++) {
      const ch = value[i];
      if (isSpace(ch)) {
        if (lastWasSpace) continue;
        text += " ";
        map.push({ node, offset: i });
        lastWasSpace = true;
      } else {
        text += ch;
        map.push({ node, offset: i });
        lastWasSpace = false;
      }
    }
  }

  const hits: number[] = [];
  for (
    let at = text.indexOf(needle);
    at >= 0;
    at = text.indexOf(needle, at + 1)
  )
    hits.push(at);
  if (!hits.length) return null;

  let pick: number | null = hits.length === 1 ? hits[0] : null;
  if (pick == null) {
    const prefixTail = normalize(q.prefix ?? "")
      .slice(-CONTEXT)
      .toLowerCase();
    const suffixHead = normalize(q.suffix ?? "")
      .slice(0, CONTEXT)
      .toLowerCase();
    let top = 0;
    const scored = hits.map((at) => {
      const before = text
        .slice(Math.max(0, at - 3 * CONTEXT), at)
        .toLowerCase();
      const after = text
        .slice(at + needle.length, at + needle.length + 3 * CONTEXT)
        .toLowerCase();
      let score = 0;
      if (prefixTail && before.includes(prefixTail)) score += 1;
      if (suffixHead && after.includes(suffixHead)) score += 1;
      top = Math.max(top, score);
      return { at, score };
    });
    const best = scored.filter((s) => s.score === top);
    if (top === 0 || best.length !== 1) return null;
    pick = best[0].at;
  }

  const start = map[pick];
  const end = map[pick + needle.length - 1];
  const range = doc.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset + 1);
  return range;
}

/**
 * Verify every anchor against the book and heal the ones that moved.
 * Best-effort and read-only: the caller applies the report. `liveDocs`
 * supplies rendered section documents (the current one) so a heal there
 * yields a CFI on the very DOM being drawn; other sections are parsed on
 * demand and cached for the sweep.
 */
export async function verifyAnchors(
  book: Book,
  items: AnchorInput[],
  options: { liveDocs?: Map<number, Document>; signal?: AbortSignal } = {},
): Promise<AnchorReport> {
  const { liveDocs, signal } = options;
  const healed: HealedAnchor[] = [];
  const broken: string[] = [];
  const docs = new Map<number, Document | null>();

  const docFor = async (index: number): Promise<Document | null> => {
    const live = liveDocs?.get(index);
    if (live) return live;
    if (docs.has(index)) return docs.get(index) ?? null;
    let doc: Document | null = null;
    try {
      doc = (await book.sections[index]?.createDocument()) ?? null;
    } catch {
      doc = null;
    }
    docs.set(index, doc);
    return doc;
  };

  const cfiFor = (index: number, range: Range) =>
    CFI.joinIndir(
      book.sections[index]?.cfi ?? CFI.fake.fromIndex(index),
      // A live (rendered) document may carry upright-number wrappers.
      cfiFromRange(range),
    );

  const resolvedIndex = (cfi: string): number | null => {
    try {
      const index = book.resolveCFI(cfi).index;
      return index >= 0 ? index : null;
    } catch {
      return null;
    }
  };

  const intact = (cfi: string, doc: Document, text: string): boolean => {
    try {
      const range = book.resolveCFI(cfi).anchor;
      const r = typeof range === "function" ? range(doc) : null;
      return (
        !!r &&
        typeof r === "object" &&
        "toString" in r &&
        normalize(String(r)) === normalize(text)
      );
    } catch {
      return false;
    }
  };

  for (const item of items) {
    if (signal?.aborted) break;
    const home = resolvedIndex(item.cfi) ?? item.sectionIndex ?? null;
    if (home != null) {
      const doc = await docFor(home);
      if (doc && intact(item.cfi, doc, item.text)) continue; // anchor intact
      const range = doc ? findQuote(doc, item) : null;
      if (range) {
        healed.push({
          id: item.id,
          oldCfi: item.cfi,
          cfi: cfiFor(home, range),
          sectionIndex: home,
        });
        continue;
      }
    }
    // The quote left its section (file re-split) — sweep the whole spine.
    let found = false;
    for (let i = 0; i < book.sections.length && !found; i++) {
      if (i === home || signal?.aborted) continue;
      const doc = await docFor(i);
      const range = doc ? findQuote(doc, item) : null;
      if (range) {
        healed.push({
          id: item.id,
          oldCfi: item.cfi,
          cfi: cfiFor(i, range),
          sectionIndex: i,
        });
        found = true;
      }
    }
    if (!found && !signal?.aborted) broken.push(item.id);
  }
  return { healed, broken };
}
