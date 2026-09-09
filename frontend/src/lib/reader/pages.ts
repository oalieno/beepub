/**
 * The pages of a pre-paginated book, read from its spine. Each entry names
 * the image the page shows, so an image pager draws the pictures directly
 * instead of laying the wrapper XHTML out. A comic packed from a CBZ and a
 * bought image-only manga EPUB come out as the same list; the server's
 * /pages route computes the same thing for third-party clients.
 */
import type { Book } from "./core";
import type { BookLoader } from "./loaders/types";
import * as CFI from "./vendor/foliate/epubcfi.js";

export type SpreadHint = "left" | "right" | "center" | null;

export interface PageEntry {
  /** Position in the page list (spine order). */
  index: number;
  /** Spine index the page is (a page is one spine item). */
  sectionIndex: number;
  /** The wrapper XHTML's path in the book. */
  href: string;
  /** The image's path in the book; null for a page without one. */
  image: string | null;
  /** Pixel size from the page's viewport meta, when it declares one. */
  width: number | null;
  height: number | null;
  spread: SpreadHint;
  linear: boolean;
  /** Point CFI of the page's body — the position the reader stores, in the
   *  same shape the current reader restores from. */
  cfi: string;
}

const IMG_RE = /<img\b[^>]*?\ssrc=["']([^"']+)["']/i;
const SVG_IMAGE_RE =
  /<(?:svg:)?image\b[^>]*?\s(?:xlink:)?href=["']([^"']+)["']/i;
const VIEWPORT_RE =
  /<meta\b[^>]*?\bname=["']viewport["'][^>]*?\bcontent=["']([^"']*)["']/i;
const SIZE_RE = /(width|height)\s*=\s*(\d+)/gi;

export function isPrePaginated(book: Pick<Book, "rendition">): boolean {
  return book.rendition?.layout === "pre-paginated";
}

function viewportSize(text: string): [number, number] | null {
  const meta = VIEWPORT_RE.exec(text);
  if (!meta) return null;
  const found: Record<string, number> = {};
  for (const m of meta[1].matchAll(SIZE_RE))
    found[m[1].toLowerCase()] = Number(m[2]);
  return found.width && found.height ? [found.width, found.height] : null;
}

/** The book's pages in spine order. Sections are read through the loader
 *  as text; nothing is rendered. */
export async function readPages(
  book: Book,
  loader: BookLoader,
): Promise<PageEntry[]> {
  const pages: PageEntry[] = [];
  const results = await Promise.all(
    book.sections.map(async (section) => {
      try {
        return await loader.loadText(section.id);
      } catch {
        return null;
      }
    }),
  );
  book.sections.forEach((section, sectionIndex) => {
    const text = results[sectionIndex] ?? "";
    const match = IMG_RE.exec(text) ?? SVG_IMAGE_RE.exec(text);
    let image: string | null = null;
    if (match) {
      const raw = match[1].split("#")[0].split("?")[0];
      image = section.resolveHref ? section.resolveHref(raw) : raw;
    }
    const size = viewportSize(text);
    const spread = (section as { pageSpread?: SpreadHint }).pageSpread ?? null;
    pages.push({
      index: pages.length,
      sectionIndex,
      href: section.id,
      image,
      width: size?.[0] ?? null,
      height: size?.[1] ?? null,
      spread,
      linear: section.linear !== "no",
      cfi: CFI.joinIndir(section.cfi ?? CFI.fake.fromIndex(sectionIndex), "/4"),
    });
  });
  return pages;
}

/** Whether a page is wider than tall — a two-page spread scanned as one
 *  image, shown alone. Unknown sizes count as portrait. */
export function isWide(page: Pick<PageEntry, "width" | "height">): boolean {
  return page.width != null && page.height != null && page.width > page.height;
}

/**
 * Group pages into what one screen shows, in reading order. Single-page
 * layout: one page per screen. Two-page layout follows the rule shared
 * with KOReader: the first page (the cover) alone, a wide page alone, and
 * portrait pages paired. The spread hints commercial EPUBs carry are not
 * consulted: the owner asked for pairs on any screen, and a book whose
 * hints disagree with its pages would otherwise never pair at all.
 *
 * Each group lists its pages in reading order; `displayOrder` turns that
 * into left-to-right for the screen.
 */
export function buildSpreads(
  pages: readonly PageEntry[],
  twoPage: boolean,
  rtl: boolean,
): PageEntry[][] {
  if (!twoPage) return pages.map((p) => [p]);
  void rtl;
  const out: PageEntry[][] = [];
  let i = 0;
  while (i < pages.length) {
    const p = pages[i];
    const q = pages[i + 1];
    const alone = i === 0 || isWide(p) || !q || isWide(q);
    if (alone) {
      out.push([p]);
      i += 1;
    } else {
      out.push([p, q]);
      i += 2;
    }
  }
  return out;
}

/** A spread's pages left-to-right on screen. */
export function displayOrder(spread: PageEntry[], rtl: boolean): PageEntry[] {
  return rtl ? [...spread].reverse() : spread;
}

export function spreadIndexOf(
  spreads: readonly PageEntry[][],
  pageIndex: number,
): number {
  const at = spreads.findIndex((s) => s.some((p) => p.index === pageIndex));
  return at >= 0 ? at : 0;
}

/** Reading progress of a page across the book, 0..100 — the last page is
 *  100 so a finished comic reads as finished. */
export function pagePercent(pageIndex: number, total: number): number {
  if (total <= 1) return 100;
  return Math.min(100, Math.max(0, (pageIndex / (total - 1)) * 100));
}

export function pageFromPercent(pct: number, total: number): number {
  if (total <= 1) return 0;
  const clamped = Math.min(100, Math.max(0, pct));
  return Math.round((clamped / 100) * (total - 1));
}

/** How the pager shows a book (Tachidesk's set): one page per screen,
 *  two side by side, or a continuous strip — vertical with gaps,
 *  horizontal with gaps (reading-direction aware), or webtoon (vertical,
 *  edge to edge, no gaps). */
export type PagerMode =
  | "single"
  | "double"
  | "vertical"
  | "horizontal"
  | "webtoon";
/** Reading direction: the book's own, or forced either way. */
export type PagerDirection = "auto" | "ltr" | "rtl";
