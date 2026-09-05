/**
 * ReaderCore — the glue between a parsed `book` and the paginator. It
 * replaces foliate's view.js with only what BeePub needs: open, navigate,
 * style, and report relocations as CFIs.
 *
 * It owns no geometry. The paginator's container rect and CSS variables
 * are the only size inputs; positions are intents (Range / fraction) that
 * the paginator re-derives after every layout change. Nothing in this file
 * stores a scroll offset or waits on a timer (.docs/reader-ng.md §2 ①–⑦).
 *
 * Browser-only: the paginator module defines a custom element at import
 * time, so consumers must import this file dynamically from onMount.
 */
import "./vendor/foliate/paginator.js";
import { EPUB } from "./vendor/foliate/epub.js";
import * as CFI from "./vendor/foliate/epubcfi.js";
import { Overlayer } from "./vendor/foliate/overlayer.js";
import { searchMatcher } from "./vendor/foliate/search.js";
import { textWalker } from "./vendor/foliate/text-walker.js";
import type { BookLoader } from "./loaders/types";

export type OverlayerInstance = InstanceType<typeof Overlayer>;

// ---------------------------------------------------------------- contracts

/** Navigation target as the paginator consumes it. `anchor` is a fraction
 *  of the section, or a function of the loaded document yielding the
 *  Range/Element to scroll to. */
export interface NavTarget {
  index: number;
  anchor?: number | ((doc: Document) => Range | Element | number | null);
}

export interface TocItem {
  label: string;
  href: string;
  subitems?: TocItem[] | null;
}

export interface BookSection {
  id: string;
  load(): Promise<string>;
  unload(): void;
  createDocument(): Promise<Document>;
  size: number;
  cfi?: string;
  linear?: string;
  resolveHref?(href: string): string;
}

/** The parser-side contract (foliate's `book`). Only the members the core
 *  touches are typed; a future TXT/CBZ parser implements this shape. */
export interface Book {
  sections: BookSection[];
  dir?: string;
  toc?: TocItem[];
  metadata?: {
    title?: unknown;
    language?: string | string[];
    [key: string]: unknown;
  };
  rendition?: { layout?: string };
  resources?: { manifest?: { href: string; mediaType?: string }[] };
  resolveCFI(cfi: string): NavTarget;
  resolveHref(href: string): NavTarget | null;
  isExternal?(href: string): boolean;
  destroy?(): void;
}

/** The renderer-side contract (foliate `<foliate-paginator>`). */
export interface PaginatorElement extends HTMLElement {
  open(book: Book): void;
  goTo(target: NavTarget): Promise<void>;
  prev(distance?: number): Promise<void>;
  next(distance?: number): Promise<void>;
  setStyles(styles: string | [string, string]): void;
  getContents(): {
    index: number;
    doc: Document;
    overlayer?: OverlayerInstance;
  }[];
  /** Finger-follow paging: the paginator overrides Element.scrollBy(dx, dy)
   *  to move the page by a finger delta (previous − current, px) within the
   *  section's bounds; snap() then settles on the nearest page, biased by
   *  the release velocity (px/ms). */
  snap(vx: number, vy: number): void;
  scrollToAnchor(
    anchor: Range | Element | number,
    select?: boolean,
  ): Promise<void>;
  destroy(): void;
}

export interface Relocation {
  /** 'page' | 'snap' | 'scroll' (user moves) · 'navigation' | 'anchor' |
   *  'selection' (programmatic). */
  reason: string;
  index: number;
  /** Position within the section, 0..1. */
  fraction: number;
  /** One page as a fraction of the section (paginated only). */
  size?: number;
  range: Range | null;
  /** Range CFI of the visible text. */
  cfi: string;
  /** Point CFI of where the visible text starts — the reading position
   *  as the current reader stores it. */
  startCfi: string;
}

/** Layout parameters. Each maps to one paginator attribute, which the
 *  paginator turns into a CSS custom property it reads back at render —
 *  JS declares, CSS decides. */
export interface LayoutParams {
  /** Inline-axis padding (and the column gap), px. The paginator also
   *  accepts a percent of the container; BeePub always sends px so the
   *  value survives container resizes without a re-push. */
  gap?: number;
  /** Block-axis outer margin, px. */
  margin?: number;
  /** Max text column width, px. */
  maxInlineSize?: number;
  /** Max text column height, px. */
  maxBlockSize?: number;
  maxColumnCount?: number;
}

/** How a page turn moves: instant jump (BeePub's historical behaviour),
 *  a 300ms slide, or the page following the finger and snapping on
 *  release (the slide also applies to that snap). */
export type PageTurnMode = "instant" | "animated" | "follow";

export interface ReaderCoreHandlers {
  onload?: (detail: { doc: Document; index: number }) => void;
  onrelocate?: (detail: Relocation) => void;
  /** A section's overlayer (SVG over the iframe, redrawn by the paginator
   *  after every expand) is ready — fires after `onload` for the same
   *  section. */
  onoverlayer?: (detail: {
    doc: Document;
    index: number;
    overlayer: OverlayerInstance;
  }) => void;
  /** An internal link was activated in section `index` (`href` already
   *  resolved against the section). Return true to take it over;
   *  otherwise the core navigates to it. External links open in a new
   *  tab and never reach this. */
  onlink?: (detail: {
    href: string;
    index: number;
    anchor: HTMLAnchorElement;
  }) => boolean | void;
}

/** One search hit: where it is and the text around it. */
export interface SearchHit {
  index: number;
  cfi: string;
  excerpt: string;
}

/** number = section index · string = CFI or href · object = section +
 *  fraction within it. */
export type NavInput = string | number | { index: number; fraction?: number };

// ------------------------------------------------------------------ helpers

function languageInfo(lang: string | string[] | undefined) {
  const first = Array.isArray(lang) ? lang[0] : lang;
  if (!first)
    return {} as { canonical?: string; isCJK?: boolean; direction?: string };
  try {
    const canonical = Intl.getCanonicalLocales(first)[0];
    const locale = new Intl.Locale(canonical);
    const isCJK = ["zh", "ja", "ko"].includes(locale.language);
    const info = locale as unknown as {
      getTextInfo?: () => { direction?: string };
      textInfo?: { direction?: string };
    };
    const direction = (info.getTextInfo?.() ?? info.textInfo)?.direction;
    return { canonical, isCJK, direction };
  } catch {
    return {};
  }
}

/**
 * The point at the first non-whitespace character at or after the start
 * of `range` (its start as-is when that is not a text node, or only
 * whitespace follows). A visible range routinely starts on the space a
 * line broke at, whose zero-width box hangs at the end of the previous
 * page: a position recorded there — or navigated to — lands one page
 * early. Positions are recorded and restored through this.
 */
function textStart(range: Range): Range {
  const point = range.cloneRange();
  point.collapse(true);
  const node = point.startContainer;
  if (node.nodeType !== Node.TEXT_NODE) return point;
  const text = node.textContent ?? "";
  let i = point.startOffset;
  while (i < text.length && /\s/.test(text[i])) i++;
  if (i > point.startOffset && i < text.length) {
    point.setStart(node, i);
    point.collapse(true);
  }
  return point;
}

/** A navigation target whose anchor resolves to a collapsed Range is
 *  moved off leading whitespace (see textStart). */
function withTextStart(target: NavTarget): NavTarget {
  const { anchor } = target;
  if (typeof anchor !== "function") return target;
  return {
    ...target,
    anchor: (doc) => {
      const result = anchor(doc);
      // Cross-realm: the section's Range class is not this window's.
      return result &&
        typeof result === "object" &&
        "collapsed" in result &&
        (result as Range).collapsed
        ? textStart(result as Range)
        : result;
    },
  };
}

const ATTR_FOR: Record<keyof LayoutParams, string> = {
  gap: "gap",
  margin: "margin",
  maxInlineSize: "max-inline-size",
  maxBlockSize: "max-block-size",
  maxColumnCount: "max-column-count",
};

function attrValue(key: keyof LayoutParams, value: number): string {
  switch (key) {
    case "maxColumnCount":
      return String(value);
    default:
      return `${value}px`;
  }
}

// --------------------------------------------------------------------- core

export class ReaderCore {
  readonly paginator: PaginatorElement;
  book: Book | null = null;
  lastLocation: Relocation | null = null;
  /** Writing mode of the current section, from its computed style. */
  vertical = false;
  /** The current section's own direction (body dir / CSS direction),
   *  the same reading the paginator lays its columns out by. */
  sectionRtl = false;
  pageTurn: PageTurnMode = "instant";

  #handlers: ReaderCoreHandlers;
  #language: ReturnType<typeof languageInfo> = {};
  #pristineDocs = new Map<number, Promise<Document | null>>();
  /** Direction inferred for a book that declares no page progression:
   *  leftward once vertical text (or rtl columns) has been seen — in its
   *  stylesheets or first section at load, or in any section rendered
   *  since. Sticky for the session, so a horizontal illustration plate
   *  cannot flip the mapping back (and forth) the way a per-section
   *  reading did. */
  #inferredLeftward = false;

  constructor(container: HTMLElement, handlers: ReaderCoreHandlers = {}) {
    this.#handlers = handlers;
    this.paginator = document.createElement(
      "foliate-paginator",
    ) as unknown as PaginatorElement;
    this.paginator.addEventListener("load", (e) =>
      this.#onLoad((e as CustomEvent).detail),
    );
    this.paginator.addEventListener("relocate", (e) =>
      this.#onRelocate((e as CustomEvent).detail),
    );
    this.paginator.addEventListener("create-overlayer", (e) =>
      this.#onCreateOverlayer((e as CustomEvent).detail),
    );
    container.append(this.paginator);
  }

  /** Parse the book through `loader` and hand it to the paginator.
   *  Nothing is displayed until goTo(). */
  async load(loader: BookLoader): Promise<Book> {
    // sha1 undefined = foliate's WebCrypto default (font deobfuscation keys)
    const book = (await new EPUB({
      ...loader,
      sha1: undefined,
    }).init()) as unknown as Book;
    this.book = book;
    this.#language = languageInfo(book.metadata?.language);
    this.#inferredLeftward = false;
    if (book.dir !== "rtl" && book.dir !== "ltr")
      void this.#inferDirection(loader);
    this.paginator.open(book);
    return book;
  }

  /** Look for vertical text before anything renders: the manifest's
   *  stylesheets and the first linear section's markup (inline styles).
   *  A book that opens on a horizontal plate is thereby read leftward
   *  from its first page turn. Sections rendered later refine this. */
  async #inferDirection(loader: BookLoader) {
    const book = this.book;
    if (!book) return;
    const sheets = (book.resources?.manifest ?? []).filter(
      (item) => item.mediaType === "text/css",
    );
    const first = book.sections[this.firstLinearIndex()];
    const hrefs = [...sheets.map((item) => item.href), first?.id].filter(
      (href): href is string => !!href,
    );
    for (const href of hrefs) {
      if (this.book !== book) return; // destroyed or reopened meanwhile
      let text: string | null = null;
      try {
        text = await loader.loadText(href);
      } catch {
        text = null;
      }
      if (text && /writing-mode\s*:\s*vertical-rl/i.test(text)) {
        this.#inferredLeftward = true;
        this.#applyPageTurn();
        return;
      }
    }
  }

  /** load() then show `target`, falling back to the first linear section
   *  when the target does not resolve. */
  async open(loader: BookLoader, target?: NavInput | null): Promise<Book> {
    const book = await this.load(loader);
    const resolved = target != null ? this.resolve(target) : null;
    await this.paginator.goTo(resolved ?? { index: this.firstLinearIndex() });
    return book;
  }

  firstLinearIndex(): number {
    const i = this.book?.sections.findIndex((s) => s.linear !== "no") ?? 0;
    return i < 0 ? 0 : i;
  }

  lastLinearIndex(): number {
    const sections = this.book?.sections ?? [];
    for (let i = sections.length - 1; i >= 0; i--) {
      if (sections[i].linear !== "no") return i;
    }
    return Math.max(0, sections.length - 1);
  }

  /** null when the target names nothing in this book (unknown section,
   *  href, or a CFI whose spine step no longer matches). */
  resolve(target: NavInput): NavTarget | null {
    const book = this.book;
    if (!book) return null;
    let resolved: NavTarget | null;
    if (typeof target === "number") resolved = { index: target };
    else if (typeof target === "object") {
      resolved = { index: target.index, anchor: target.fraction ?? 0 };
    } else if (CFI.isCFI.test(target)) {
      try {
        resolved = book.resolveCFI(target);
      } catch {
        resolved = null;
      }
    } else resolved = book.resolveHref(target);
    if (!resolved) return null;
    const { index } = resolved;
    if (!Number.isInteger(index) || index < 0 || index >= book.sections.length)
      return null;
    return resolved;
  }

  /** Rejects when the target resolves to a section but not to a place in
   *  it (a CFI whose in-document path no longer exists). */
  async goTo(target: NavInput): Promise<NavTarget | null> {
    const resolved = this.resolve(target);
    if (!resolved) return null;
    await this.paginator.goTo(withTextStart(resolved));
    return resolved;
  }

  prev() {
    return this.paginator.prev();
  }

  next() {
    return this.paginator.next();
  }

  /**
   * Whether the book advances leftward — the physical→reading direction
   * every gesture and arrow maps through. The book's declared page
   * progression rules for all of it (a vertical-rl novel's horizontal
   * illustration page still turns leftward; the epub.js reader and
   * upstream foliate do the same). A book that declares nothing gets one
   * book-level inference for the session (see #inferredLeftward) — never
   * a per-section reading, which flips at every plate.
   */
  advancesLeftward(): boolean {
    const dir = this.book?.dir;
    if (dir === "rtl") return true;
    if (dir === "ltr") return false;
    return this.#inferredLeftward;
  }

  /** Whether the section on screen is laid out to advance leftward
   *  (vertical writing, or rtl columns). */
  sectionAdvancesLeftward(): boolean {
    return this.vertical || this.sectionRtl;
  }

  goLeft() {
    return this.advancesLeftward() ? this.next() : this.prev();
  }

  goRight() {
    return this.advancesLeftward() ? this.prev() : this.next();
  }

  setPageTurn(mode: PageTurnMode) {
    this.pageTurn = mode;
    this.#applyPageTurn();
  }

  /**
   * The page-turn mode that applies to the section on screen. The slide
   * and finger-follow modes move the paginator's scroll axis, which for
   * vertical text runs top to bottom (pages are stacked vertically) and
   * for a section laid out against the book's direction runs the wrong
   * way — both would slide the page across the finger's motion, so such
   * sections turn instantly whatever the setting says.
   */
  effectivePageTurn(): PageTurnMode {
    if (this.pageTurn === "instant") return "instant";
    if (this.vertical) return "instant";
    if (this.sectionAdvancesLeftward() !== this.advancesLeftward())
      return "instant";
    return this.pageTurn;
  }

  #applyPageTurn() {
    // The paginator animates page turns and snaps only while `animated`
    // is present; finger-follow wants the animated snap on release.
    this.paginator.toggleAttribute(
      "animated",
      this.effectivePageTurn() !== "instant",
    );
  }

  /** Finger-follow paging passthroughs (see PageTurnMode). */
  scrollBy(dx: number, dy: number) {
    this.paginator.scrollBy(dx, dy);
  }

  snap(vx: number, vy: number) {
    this.paginator.snap(vx, vy);
  }

  /** CSS injected into every section. A pair is [before, after]: `before`
   *  is prepended to <head> (the book's own styles win), `after` appended
   *  (ours win at equal specificity). */
  setStyles(styles: string | [string, string]) {
    this.paginator.setStyles(styles);
  }

  /** Declare layout parameters. Only changed values are written, so a
   *  re-declaration of the same layout triggers no re-render. */
  setLayout(params: LayoutParams) {
    for (const key of Object.keys(params) as (keyof LayoutParams)[]) {
      const value = params[key];
      if (value == null) continue;
      const attr = ATTR_FOR[key];
      const next = attrValue(key, value);
      if (this.paginator.getAttribute(attr) !== next) {
        this.paginator.setAttribute(attr, next);
      }
    }
  }

  /** The point CFI at the start of a range CFI (a point CFI is returned
   *  as-is). */
  collapseCFI(cfi: string): string {
    try {
      return CFI.collapse(cfi);
    } catch {
      return cfi;
    }
  }

  cfiOf(index: number, range: Range | null): string {
    const base = this.book?.sections[index]?.cfi ?? CFI.fake.fromIndex(index);
    if (!range) return base;
    return CFI.joinIndir(base, CFI.fromRange(range));
  }

  currentCFI(): string | null {
    return this.lastLocation?.cfi ?? null;
  }

  /** Index of the section on screen (null before the first render). */
  currentIndex(): number | null {
    return this.paginator.getContents()[0]?.index ?? null;
  }

  getContents() {
    return this.paginator.getContents();
  }

  /** A section's parsed, unrendered document — the DOM that kosync
   *  xpointers, footnote lookups and anything else structural read,
   *  free of the styles and overlays the rendered copy carries. Parsed
   *  once per section; null when the section fails to load. */
  pristineDocument(index: number): Promise<Document | null> {
    let pending = this.#pristineDocs.get(index);
    if (!pending) {
      const section = this.book?.sections[index];
      pending = (section ? section.createDocument() : Promise.resolve(null))
        .then((doc) => doc ?? null)
        .catch(() => null);
      this.#pristineDocs.set(index, pending);
    }
    return pending;
  }

  /**
   * Search the whole book, one section per step: each yield carries a
   * section's hits (possibly none) so a consumer can show results as they
   * come. Matching is foliate's — case- and diacritic-insensitive,
   * grapheme-granular, in the book's language. Ranges come from a fresh
   * parse of each section (not the pristine cache: a full-book search
   * should not pin every document in memory) and are reported as CFIs,
   * which resolve identically in the rendered copy.
   */
  async *search(
    query: string,
    signal?: AbortSignal,
  ): AsyncGenerator<{ index: number; hits: SearchHit[] }> {
    const book = this.book;
    if (!book) return;
    const matcher = searchMatcher(textWalker, {
      defaultLocale: this.#language.canonical ?? "en",
      matchCase: false,
      matchDiacritics: false,
      matchWholeWords: false,
    });
    for (let index = 0; index < book.sections.length; index++) {
      if (signal?.aborted) return;
      let doc: Document | null = null;
      try {
        doc = await book.sections[index].createDocument();
      } catch {
        doc = null;
      }
      if (!doc?.body) continue;
      const hits: SearchHit[] = [];
      for (const { range, excerpt } of matcher(doc, query)) {
        if (signal?.aborted) return;
        hits.push({
          index,
          cfi: this.cfiOf(index, range),
          excerpt: `${excerpt.pre}${excerpt.match}${excerpt.post}`,
        });
      }
      yield { index, hits };
    }
  }

  destroy() {
    try {
      this.paginator.destroy();
    } catch {
      // destroy() before the first section loaded has no view to tear down
    }
    this.paginator.remove();
    this.#pristineDocs.clear();
    this.book?.destroy?.();
    this.book = null;
  }

  #onLoad({ doc, index }: { doc: Document; index: number }) {
    const root = doc.documentElement;
    root.lang ||= this.#language.canonical ?? "";
    if (!this.#language.isCJK) root.dir ||= this.#language.direction ?? "";
    const style = doc.defaultView?.getComputedStyle(doc.body);
    const writingMode = style?.writingMode;
    this.vertical = !!writingMode && writingMode.startsWith("vertical");
    // Mirrors the paginator's own getDirection() — read here because the
    // load event precedes the render that stamps the paginator's `dir`.
    this.sectionRtl = doc.body.dir === "rtl" || style?.direction === "rtl";
    if (this.vertical || this.sectionRtl) this.#inferredLeftward = true;
    this.#applyPageTurn();
    this.#handleLinks(doc, index);
    this.#handlers.onload?.({ doc, index });
  }

  #onCreateOverlayer({
    doc,
    index,
    attach,
  }: {
    doc: Document;
    index: number;
    attach: (overlayer: OverlayerInstance) => void;
  }) {
    const overlayer = new Overlayer();
    attach(overlayer);
    this.#handlers.onoverlayer?.({ doc, index, overlayer });
  }

  #handleLinks(doc: Document, index: number) {
    const book = this.book;
    const section = book?.sections[index];
    doc.addEventListener("click", (e) => {
      const a = (e.target as Element | null)?.closest?.("a[href]");
      if (!a) return;
      e.preventDefault();
      const raw = a.getAttribute("href") ?? "";
      const href = section?.resolveHref?.(raw) ?? raw;
      if (book?.isExternal?.(href)) {
        globalThis.open(raw, "_blank");
        return;
      }
      if (
        this.#handlers.onlink?.({
          href,
          index,
          anchor: a as HTMLAnchorElement,
        })
      )
        return;
      this.goTo(href).catch((err) => console.error(err));
    });
  }

  #onRelocate(detail: {
    reason: string;
    index: number;
    fraction?: number;
    size?: number;
    range?: Range | null;
  }) {
    const range = detail.range ?? null;
    const cfi = this.cfiOf(detail.index, range);
    const location: Relocation = {
      reason: detail.reason,
      index: detail.index,
      fraction: detail.fraction ?? 0,
      size: detail.size,
      range,
      cfi,
      startCfi: range ? this.cfiOf(detail.index, textStart(range)) : cfi,
    };
    this.lastLocation = location;
    this.#handlers.onrelocate?.(location);
  }
}
