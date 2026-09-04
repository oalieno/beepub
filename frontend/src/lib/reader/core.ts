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
import type { BookLoader } from "./loaders/server";

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
  cfi: string;
}

/** Layout parameters. Each maps to one paginator attribute, which the
 *  paginator turns into a CSS custom property it reads back at render —
 *  JS declares, CSS decides. */
export interface LayoutParams {
  /** Inline padding and column gap, percent of the container. */
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

const ATTR_FOR: Record<keyof LayoutParams, string> = {
  gap: "gap",
  margin: "margin",
  maxInlineSize: "max-inline-size",
  maxBlockSize: "max-block-size",
  maxColumnCount: "max-column-count",
};

function attrValue(key: keyof LayoutParams, value: number): string {
  switch (key) {
    case "gap":
      return `${value}%`;
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
  pageTurn: PageTurnMode = "instant";

  #handlers: ReaderCoreHandlers;
  #language: ReturnType<typeof languageInfo> = {};

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

  /** Parse the book through `loader`, hand it to the paginator, and show
   *  `target` (default: the first linear section). */
  async open(loader: BookLoader, target?: NavInput | null): Promise<Book> {
    // sha1 undefined = foliate's WebCrypto default (font deobfuscation keys)
    const book = (await new EPUB({
      ...loader,
      sha1: undefined,
    }).init()) as unknown as Book;
    this.book = book;
    this.#language = languageInfo(book.metadata?.language);
    this.paginator.open(book);
    const resolved = target != null ? this.resolve(target) : null;
    await this.paginator.goTo(resolved ?? { index: this.firstLinearIndex() });
    return book;
  }

  firstLinearIndex(): number {
    const i = this.book?.sections.findIndex((s) => s.linear !== "no") ?? 0;
    return i < 0 ? 0 : i;
  }

  resolve(target: NavInput): NavTarget | null {
    const book = this.book;
    if (!book) return null;
    if (typeof target === "number") return { index: target };
    if (typeof target === "object") {
      return { index: target.index, anchor: target.fraction ?? 0 };
    }
    if (CFI.isCFI.test(target)) return book.resolveCFI(target);
    return book.resolveHref(target);
  }

  async goTo(target: NavInput): Promise<NavTarget | null> {
    const resolved = this.resolve(target);
    if (!resolved) return null;
    await this.paginator.goTo(resolved);
    return resolved;
  }

  prev() {
    return this.paginator.prev();
  }

  next() {
    return this.paginator.next();
  }

  /** Physical direction → reading direction. Vertical-rl and rtl books
   *  advance leftward. */
  #backwardIsRight(): boolean {
    return this.vertical || this.paginator.getAttribute("dir") === "rtl";
  }

  goLeft() {
    return this.#backwardIsRight() ? this.next() : this.prev();
  }

  goRight() {
    return this.#backwardIsRight() ? this.prev() : this.next();
  }

  setPageTurn(mode: PageTurnMode) {
    this.pageTurn = mode;
    // The paginator animates page turns and snaps only while `animated`
    // is present; finger-follow wants the animated snap on release.
    this.paginator.toggleAttribute("animated", mode !== "instant");
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

  destroy() {
    try {
      this.paginator.destroy();
    } catch {
      // destroy() before the first section loaded has no view to tear down
    }
    this.paginator.remove();
    this.book?.destroy?.();
    this.book = null;
  }

  #onLoad({ doc, index }: { doc: Document; index: number }) {
    const root = doc.documentElement;
    root.lang ||= this.#language.canonical ?? "";
    if (!this.#language.isCJK) root.dir ||= this.#language.direction ?? "";
    const writingMode = doc.defaultView?.getComputedStyle(doc.body).writingMode;
    this.vertical = !!writingMode && writingMode.startsWith("vertical");
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
      } else {
        this.goTo(href).catch((err) => console.error(err));
      }
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
    const location: Relocation = {
      reason: detail.reason,
      index: detail.index,
      fraction: detail.fraction ?? 0,
      size: detail.size,
      range,
      cfi: this.cfiOf(detail.index, range),
    };
    this.lastLocation = location;
    this.#handlers.onrelocate?.(location);
  }
}
