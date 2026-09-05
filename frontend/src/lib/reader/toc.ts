/**
 * Table-of-contents helpers for the new engine, written against the
 * parser's `book` contract: every TOC href is resolved to a spine index
 * once, and "which entry is the page under" is decided by document
 * position against the visible range — no layout is read (Range is the
 * positioning primitive, .docs/reader-ng.md §2 ⑥).
 */
import type { Book, TocItem } from "./core";

export interface TocEntry {
  /** The item's own href, as the sidebar identifies entries. */
  href: string;
  label: string;
  /** Spine index the href resolves to. */
  index: number;
  /** Fragment identifier within the section, if the href has one. */
  fragment: string | null;
}

/** Depth-first flatten in TOC order (which is reading order by
 *  convention), each item resolved to its spine index. Items without an
 *  href or pointing outside the spine are dropped. */
export function flattenToc(
  book: Pick<Book, "resolveHref">,
  toc: TocItem[] | null | undefined,
): TocEntry[] {
  const out: TocEntry[] = [];
  const walk = (items: TocItem[]) => {
    for (const item of items) {
      if (item.href) {
        let index = -1;
        try {
          index = book.resolveHref(item.href)?.index ?? -1;
        } catch {
          index = -1;
        }
        if (index >= 0) {
          const hash = item.href.indexOf("#");
          out.push({
            href: item.href,
            label: item.label,
            index,
            fragment: hash >= 0 ? item.href.slice(hash + 1) : null,
          });
        }
      }
      if (item.subitems?.length) walk(item.subitems);
    }
  };
  walk(toc ?? []);
  return out;
}

function fragmentElement(doc: Document, id: string): Element | null {
  return (
    doc.getElementById(id) ?? doc.querySelector(`[name="${CSS.escape(id)}"]`)
  );
}

/** Whether `el` starts at or before `node` in document order. */
function precedes(el: Element, node: Node): boolean {
  if (el === node || el.contains(node)) return true;
  return !!(
    el.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING
  );
}

/**
 * The entry the visible page is under: the last entry (in TOC order) at
 * or before the page's start. Entries of the current section that carry a
 * fragment count only once their element is at or before the start of
 * the visible range; without a range every entry of the section counts.
 */
export function activeTocEntry(
  entries: readonly TocEntry[],
  index: number,
  range: Range | null,
): TocEntry | null {
  const start = range?.startContainer ?? null;
  const doc = start?.ownerDocument ?? null;
  let active: TocEntry | null = null;
  for (const entry of entries) {
    if (entry.index > index) continue;
    if (entry.index === index && entry.fragment && start && doc) {
      const el = fragmentElement(doc, entry.fragment);
      if (el && !precedes(el, start)) continue;
    }
    active = entry;
  }
  return active;
}

/** Label for a section without a rendered page to refine against (a seek
 *  target): the section's first entry, else the nearest entry before it. */
export function tocLabelForSection(
  entries: readonly TocEntry[],
  index: number,
): string | null {
  let before: TocEntry | null = null;
  for (const entry of entries) {
    if (entry.index === index) return entry.label;
    if (entry.index < index) before = entry;
  }
  return before?.label ?? null;
}
