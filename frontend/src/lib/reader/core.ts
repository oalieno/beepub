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
import { normalizeCFI } from "./cfi";
import { Overlayer } from "./vendor/foliate/overlayer.js";
import { searchMatcher } from "./vendor/foliate/search.js";
import { textWalker } from "./vendor/foliate/text-walker.js";
import type { BookLoader } from "./loaders/types";
import { ImagePrefetcher } from "./prefetch";
import { CoverSlide, type SlideEvent } from "./slide";
import {
  OWN_LAYOUT_ATTR,
  TCY_CSS,
  cfiFromRange,
  combineShortNumbers,
  forwardStart,
  tcyFilter,
  unwrapBoundaries,
  wholeText,
} from "./tcy";

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
  /** What open() stores: the spine, and the book's page progression. */
  sections: BookSection[];
  bookDir?: string;
  /** No page before / after the one on screen in the whole book. */
  readonly atStart: boolean;
  readonly atEnd: boolean;
  /** The page on screen and the section's page count, as the paginator
   *  counts them: a blank page pads each end, so text pages run from 1
   *  to pages − 2. Both throw before the first render. */
  readonly page: number;
  readonly pages: number;
  scrollToAnchor(
    anchor: Range | Element | number,
    select?: boolean,
  ): Promise<void>;
  /** Load the section on screen again, landing on `anchor`; `styles`
   *  become the injected styles of the new document (vendored addition). */
  reload(
    anchor: NavTarget["anchor"],
    styles?: string | [string, string],
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

/** How a page turn moves. The reader offers two: "fade" (the page fades
 *  out, the next one fades in — the default) and "slide" (one page
 *  slides over the other, following the finger; taps and keys play the
 *  same slide on their own — see slide.ts). "instant" is a bare jump
 *  with no animation, reachable only through the `?turn=instant` session
 *  override — tests and probes read the page right after a turn. */
export type PageTurnMode = "fade" | "slide" | "instant";

/** The fade of a page turn: out, jump, in. Short enough to read as a
 *  blink of the page rather than a wait. */
const FADE_OUT_MS = 40;
const FADE_IN_MS = 100;
/** The paginator drops turns for this long after one (its own lock). */
const TURN_LOCK_MS = 100;
/** How long after reaching the paginator a turn can still be inside that
 *  lock (timers run late) rather than inside a chapter load. */
const TURN_LOCK_SLACK_MS = TURN_LOCK_MS + 50;

function prefersReducedMotion(): boolean {
  try {
    return !!globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")
      .matches;
  } catch {
    return false;
  }
}

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
  /** A section loaded into one of the slide's ghosts (the inert
   *  renderings of the pages a turn away — slide.ts), before it is laid
   *  out. It has had the core's own per-section adjustments; whatever
   *  the integration layer does to a live section's look at `onload`
   *  belongs here too, and the ghosts' layout (setGhostLayout) for the
   *  writing mode reported. */
  onghostload?: (detail: {
    doc: Document;
    index: number;
    vertical: boolean;
  }) => void;
  /** A ghost's overlayer for the section it shows (`ghost` tells the
   *  ghosts apart) — or null once that ghost is gone, or, with no ghost
   *  named, all of them are. */
  onghostoverlayer?: (
    detail: {
      doc: Document;
      index: number;
      overlayer: OverlayerInstance;
    } | null,
    ghost?: object,
  ) => void;
}

/** The reader's say over a book's writing direction: the book's own, or
 *  forced horizontal / vertical (CJK books). */
export type WritingMode = "auto" | "horizontal" | "vertical";

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
 *
 * The text node is read as the book wrote it (`wholeText`): where a
 * forced vertical layout wrapped a short number, the skip runs on across
 * the wrapper exactly as it does through the unsplit node, and the point
 * is named by the piece that holds the character it stands before.
 */
function textStart(range: Range): Range {
  const point = unwrapBoundaries(range).cloneRange();
  point.collapse(true);
  const node = point.startContainer;
  if (node.nodeType !== Node.TEXT_NODE) return point;
  const whole = wholeText(node, point.startOffset);
  const { text } = whole;
  let i = whole.offset;
  while (i < text.length && /\s/.test(text[i])) i++;
  if (i >= text.length) i = whole.offset;
  const at = whole.at(i);
  if (at.node !== node || at.offset !== point.startOffset) {
    point.setStart(at.node, at.offset);
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

/**
 * The rules that force a writing mode on a section. They go last in the
 * document, important, and behind an id-weight selector, so they beat the
 * book's own rules whatever those weigh.
 *
 * The root and the body carry the mode — the paginator lays the section
 * out by the body's computed writing mode. Everything below inherits it:
 * a book that sets its writing mode on an inner container (`div.main`,
 * `.chapter-body`) instead of the body would otherwise keep a vertical
 * block inside a horizontal page (or the reverse), cut off at the page
 * edge. Inheriting is what an element does when nothing is declared, so
 * ruby, tate-chu-yoko runs, pictures and tables behave as they do in a
 * book written that way to begin with. The direction is pinned along
 * with it: these are CJK books, and a stray `direction: rtl` would run
 * the columns against the page turns.
 */
function writingModeCss(mode: WritingMode): string {
  if (mode === "auto") return "";
  const value = mode === "vertical" ? "vertical-rl" : "horizontal-tb";
  // The rules stand down while the root wears OWN_LAYOUT_ATTR: how the
  // core reads which text the book itself set vertically (#combineNumbers).
  const root = `:root:not(#beepub-writing-mode):not([${OWN_LAYOUT_ATTR}])`;
  return `
${root}, ${root} body {
  writing-mode: ${value} !important;
  direction: ltr !important;
}
${root} body * { writing-mode: inherit !important; }${
    mode === "vertical" ? TCY_CSS : ""
  }`;
}

// ------------------------------------------------------------------- plates

const PLATE_ATTR = "data-beepub-plate";

/**
 * An illustration alone in its paragraph, in vertical text, is centred
 * along the column (top to bottom on the page). The paragraph also loses
 * its line height: the strut beside a page-wide image would make the line
 * wider than the page and push the image off it.
 */
const PLATE_CSS = `
[${PLATE_ATTR}] {
  text-align: center !important;
  text-indent: 0 !important;
  line-height: 0 !important;
}`;

/** Mark the paragraphs that hold one image and no text. Attributes only,
 *  so every CFI reads the section as before. */
function markPlates(doc: Document) {
  for (const el of Array.from(doc.body.querySelectorAll("img, svg"))) {
    const block = el.parentElement;
    if (!block || block === doc.body || block.childElementCount !== 1) continue;
    if (/\S/.test(block.textContent ?? "")) continue;
    const display = doc.defaultView?.getComputedStyle(block).display;
    if (display === "block") block.setAttribute(PLATE_ATTR, "");
  }
}

// ----------------------------------------------------------------- sections

/**
 * Let more than one paginator hold a section. The parser's loader mints
 * a section's blob URL on load and revokes it on unload, and its count
 * of repeated loads of one section is not balanced (a second holder's
 * unload can revoke the URL the first is still showing). With the live
 * paginator and the slide's ghost both loading sections, every load and
 * unload is counted here instead: the parser sees one load when the
 * first holder arrives and one unload when the last has left.
 */
function shareSections(sections: BookSection[]) {
  for (const section of sections) {
    const load = section.load.bind(section);
    const unload = section.unload.bind(section);
    let holders = 0;
    let pending: Promise<string> | null = null;
    section.load = () => {
      holders++;
      if (!pending) {
        const p: Promise<string> = Promise.resolve().then(load);
        pending = p;
        // A failed load is nobody's to unload, and the next one retries.
        p.catch(() => {
          if (pending !== p) return;
          pending = null;
          holders = 0;
        });
      }
      return pending;
    };
    section.unload = () => {
      if (holders === 0) return;
      if (--holders > 0) return;
      pending = null;
      unload();
    };
  }
}

// --------------------------------------------------------------------- core

const VERTICAL_RL = /writing-mode\s*:\s*vertical-rl/i;
const CSS_BLOCK = /([^{}]+)\{([^{}]*)\}/g;
const ROOT_TAG = /<(html|body)\b([^>]*)>/gi;

/** Classes on the section's html and body tags. */
function classesOfRoot(markup: string): Set<string> {
  const out = new Set<string>();
  for (const m of markup.matchAll(ROOT_TAG)) {
    const cls = /\bclass\s*=\s*["']([^"']*)["']/i.exec(m[2]);
    for (const c of cls?.[1].split(/\s+/) ?? []) if (c) out.add(c);
  }
  return out;
}

/** Inline style attributes on the html and body tags, as declarations
 *  the selector-free path below accepts. */
function inlineRootStyles(markup: string): string[] {
  const out: string[] = [];
  for (const m of markup.matchAll(ROOT_TAG)) {
    const style = /\bstyle\s*=\s*["']([^"']*)["']/i.exec(m[2]);
    if (style) out.push(`body{${style[1]}}`);
  }
  return out;
}

function styleBlocks(markup: string): string[] {
  return [...markup.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].map(
    (m) => m[1],
  );
}

/**
 * Whether the CSS text has a vertical-rl rule that applies to the body:
 * a selector made only of html/body/:root/* (with an optional descendant
 * step), or such a selector qualified by classes the root actually
 * wears. A rule on an inner element, or on a class the body lacks, is
 * not the book's writing mode.
 */
function verticalBodyRule(css: string, rootClasses: Set<string>): boolean {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of text.matchAll(CSS_BLOCK)) {
    if (!VERTICAL_RL.test(m[2])) continue;
    // An at-rule prelude (`@charset ...;`, `@media (...) {`) may precede
    // the selector in the capture.
    const selectors = m[1].split(/[{};]/).pop()?.split(",") ?? [];
    for (const raw of selectors) {
      const selector = raw.trim();
      if (!selector || selector.startsWith("@")) continue;
      if (selectorReachesBody(selector, rootClasses)) return true;
    }
  }
  return false;
}

const COMPOUND = /^(html|body|:root|\*)?((?:\.[\w-]+)*)$/;

function selectorReachesBody(
  selector: string,
  rootClasses: Set<string>,
): boolean {
  const parts = selector.split(/\s*>\s*|\s+/).filter(Boolean);
  if (parts.length === 0 || parts.length > 2) return false;
  if (parts.length === 2 && !/^(html|:root|\*)/.test(parts[0])) return false;
  for (const part of parts) {
    const m = COMPOUND.exec(part);
    if (!m) return false;
    // A bare `.vrtl` compound may sit on the body; a bare element other
    // than html/body/:root/* never does (COMPOUND rejects those).
    if (!m[1] && !m[2]) return false;
    for (const cls of m[2].split(".").filter(Boolean)) {
      if (!rootClasses.has(cls)) return false;
    }
  }
  return true;
}

export class ReaderCore {
  readonly paginator: PaginatorElement;
  book: Book | null = null;
  lastLocation: Relocation | null = null;
  /** Writing mode of the current section, from its computed style. */
  vertical = false;
  /** The current section's own direction (body dir / CSS direction),
   *  the same reading the paginator lays its columns out by. */
  sectionRtl = false;
  pageTurn: PageTurnMode = "fade";
  /** The writing direction asked for (see setWritingMode). */
  writingMode: WritingMode = "auto";

  #styles: string | [string, string] = "";
  /** The book's own text has been seen running vertically — in its
   *  stylesheets at load, or in a section rendered as the book wrote it. */
  #nativeVertical = false;
  #handlers: ReaderCoreHandlers;
  #language: ReturnType<typeof languageInfo> = {};
  #pristineDocs = new Map<number, Promise<Document | null>>();
  /** Warms the images of the sections around the one on screen. */
  #prefetch: ImagePrefetcher | null = null;
  #prefetchIndex = -1;
  /** Direction inferred for a book that declares no page progression:
   *  leftward once vertical text (or rtl columns) has been seen — in its
   *  stylesheets or first section at load, or in any section rendered
   *  since. Sticky for the session, so a horizontal illustration plate
   *  cannot flip the mapping back (and forth) the way a per-section
   *  reading did. */
  #inferredLeftward = false;

  // A faded page turn in progress (see #turn).
  #fadeTimer: ReturnType<typeof setTimeout> | null = null;
  #fadeAnimation: Animation | null = null;
  /** Bumped whenever the fade is abandoned, so a turn still in the
   *  paginator's hands finds it is no longer the one being waited on. */
  #fadeGeneration = 0;
  /** The turn has gone to the paginator; its page is not on screen yet. */
  #awaitingPage = false;
  #turning = false;
  #turnStartedAt = 0;
  #turnAskedAt = 0;
  #queuedTurn: 1 | -1 | null = null;

  /** The slide mode's further renderings and their layers (slide.ts);
   *  only there while the mode is "slide" and a reflowable book is open. */
  #slide: CoverSlide | null = null;
  /** Which way each of its ghosts' sections is written. */
  #ghostVertical = new WeakMap<object, boolean>();
  /** A turn asked for while one the slide could not show was fading. */
  #afterFade: 1 | -1 | null = null;
  #container: HTMLElement;
  #pageColor = "";

  constructor(container: HTMLElement, handlers: ReaderCoreHandlers = {}) {
    this.#handlers = handlers;
    this.#container = container;
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
    // The parser reads through the prefetcher: bytes it warmed for the
    // sections ahead are answered from memory when the paginator turns
    // into them.
    this.#prefetch?.destroy();
    // The ghost belongs to the book it was made for.
    this.#dropSlide();
    const prefetch = new ImagePrefetcher(loader);
    this.#prefetch = prefetch;
    this.#prefetchIndex = -1;
    // sha1 undefined = foliate's WebCrypto default (font deobfuscation keys)
    const book = (await new EPUB({
      ...prefetch.loader,
      sha1: undefined,
    }).init()) as unknown as Book;
    // Every CFI the book resolves — for the paginator, the highlight
    // layer, the anchor check — reads the section with the upright-number
    // wrappers transparent (see tcy.ts); on a document without wrappers
    // the filter changes nothing.
    const resolveCFI = (
      book.resolveCFI as (cfi: string, filter?: unknown) => NavTarget
    ).bind(book);
    book.resolveCFI = (cfi: string) => {
      const target = resolveCFI(cfi, tcyFilter);
      const { anchor } = target;
      if (typeof anchor !== "function") return target;
      return {
        ...target,
        anchor: (doc) => {
          const result = anchor(doc);
          // Cross-realm: the section's Range class is not this window's.
          return result && typeof result === "object" && "collapsed" in result
            ? forwardStart(result as Range)
            : result;
        },
      };
    };
    shareSections(book.sections);
    this.book = book;
    prefetch.open(book.sections);
    this.#language = languageInfo(book.metadata?.language);
    // Whether a forced writing mode applies depends on the book's layout.
    this.paginator.setStyles(this.#composedStyles());
    this.#inferredLeftward = false;
    this.#nativeVertical = false;
    if (book.dir !== "rtl" && book.dir !== "ltr")
      void this.#inferDirection(prefetch.loader);
    this.paginator.open(book);
    this.#applyPageTurn();
    return book;
  }

  /** Look for vertical text before anything renders: the manifest's
   *  stylesheets and the first linear section's markup (inline styles).
   *  A book that opens on a horizontal plate is thereby read leftward
   *  from its first page turn. Sections rendered later refine this.
   *
   *  Only a rule that reaches the body counts, the way the paginator's
   *  own check reads the body's computed style: publishers' boilerplate
   *  sheets carry `body.vrtl { writing-mode: vertical-rl }` in every
   *  book, horizontal ones included, gated on a class the body may never
   *  wear. */
  async #inferDirection(loader: BookLoader) {
    const book = this.book;
    if (!book) return;
    const first = book.sections[this.firstLinearIndex()];
    const load = async (href: string | undefined) => {
      if (!href) return null;
      try {
        return await loader.loadText(href);
      } catch {
        return null;
      }
    };
    const markup = await load(first?.id);
    if (this.book !== book) return; // destroyed or reopened meanwhile
    const rootClasses = classesOfRoot(markup ?? "");
    const texts: string[] = [];
    if (markup) {
      texts.push(...inlineRootStyles(markup));
      texts.push(...styleBlocks(markup));
    }
    const sheets = (book.resources?.manifest ?? []).filter(
      (item) => item.mediaType === "text/css",
    );
    for (const item of sheets) {
      const css = await load(item.href);
      if (this.book !== book) return;
      if (css) texts.push(css);
    }
    if (texts.some((text) => verticalBodyRule(text, rootClasses))) {
      this.#inferredLeftward = true;
      this.#nativeVertical = true;
    }
  }

  /** load() then show `target`, falling back to the first linear section
   *  when the target does not resolve. */
  async open(loader: BookLoader, target?: NavInput | null): Promise<Book> {
    const book = await this.load(loader);
    const resolved = target != null ? this.resolve(target) : null;
    this.#cancelTurn();
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
        resolved = book.resolveCFI(normalizeCFI(target));
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
    this.#cancelTurn();
    await this.paginator.goTo(withTextStart(resolved));
    return resolved;
  }

  prev() {
    return this.#turn(-1);
  }

  next() {
    return this.#turn(1);
  }

  /**
   * One page back or forward. Only page turns come through here:
   * navigation (goTo, a writing-mode reload) never animates and abandons
   * a turn in progress.
   *
   * In the slide mode the turn is the cover slide (slide.ts); it waits a
   * moment for its second rendering when the neighbouring page is in a
   * section that is not loaded there yet, and a turn it still cannot
   * show then fades instead. A reader who asked for reduced motion,
   * and a turn that goes nowhere (first or last page), get the bare
   * paginator.
   */
  #turn(dir: 1 | -1): Promise<void> {
    const mode = this.effectivePageTurn();
    const slide =
      mode === "slide" && !prefersReducedMotion() ? this.#slide : null;
    // A slide under way takes the turn itself (it ends early and this
    // one follows), whatever the page still on screen says about edges.
    if (slide?.busy) {
      slide.turn(dir);
      return Promise.resolve();
    }
    if (mode === "instant" || prefersReducedMotion() || this.#atEdge(dir)) {
      this.#cancelTurn();
      return this.#paginatorTurn(dir);
    }
    // A fade already on its way (a turn the slide could not show): two
    // kinds of turn must not overlap, and a turn must not be lost
    // either. The latest one asked for is made when the fade is over.
    if (slide && this.#fading()) {
      this.#afterFade = dir;
      return Promise.resolve();
    }
    if (slide?.turn(dir)) return Promise.resolve();
    return this.#fadeTurn(dir);
  }

  /** A faded turn is somewhere between its fade-out and its page. */
  #fading(): boolean {
    return this.#fadeTimer != null || this.#turning || this.#awaitingPage;
  }

  /**
   * The faded turn: the page fades out, the paginator jumps, and the new
   * page fades in once it is on screen (the relocation says so — across
   * a chapter boundary that is after the load).
   *
   * Paging quickly must feel as it does without the fade. The paginator
   * drops turns for 100ms after one; the fade-out pushes that window
   * back by its own length, so a turn asked for a full lock after the
   * previous one, yet before the paginator is free again, is kept and
   * made the moment it is — at most one, never a backlog. (A turn asked
   * for while a chapter is still loading is dropped, as it always was.)
   */
  #fadeTurn(dir: 1 | -1): Promise<void> {
    const now = performance.now();
    // Fading out: the previous turn is under 40ms old.
    if (this.#fadeTimer != null) return Promise.resolve();
    if (this.#turning) {
      if (
        now - this.#turnStartedAt < TURN_LOCK_SLACK_MS &&
        now - this.#turnAskedAt >= TURN_LOCK_MS
      ) {
        this.#queuedTurn = dir;
        this.#turnAskedAt = now;
      }
      return Promise.resolve();
    }
    this.#turnAskedAt = now;
    this.#fade(0, FADE_OUT_MS);
    this.#fadeTimer = setTimeout(() => {
      this.#fadeTimer = null;
      this.#fadedTurn(dir);
    }, FADE_OUT_MS);
    return Promise.resolve();
  }

  #paginatorTurn(dir: 1 | -1): Promise<void> {
    return dir < 0 ? this.paginator.prev() : this.paginator.next();
  }

  /** Nothing to turn to: no fade for a turn that goes nowhere. */
  #atEdge(dir: 1 | -1): boolean {
    try {
      return dir < 0 ? this.paginator.atStart : this.paginator.atEnd;
    } catch {
      return false; // nothing rendered yet
    }
  }

  #fadedTurn(dir: 1 | -1) {
    const generation = this.#fadeGeneration;
    this.#turning = true;
    this.#turnStartedAt = performance.now();
    this.#awaitingPage = true;
    const done = () => {
      if (generation !== this.#fadeGeneration) return;
      this.#turning = false;
      // The paginator refused the turn (nothing relocated): the page
      // that faded out comes back.
      this.#showPage();
      const queued = this.#queuedTurn;
      this.#queuedTurn = null;
      if (queued) {
        this.#fadedTurn(queued);
        return;
      }
      const kept = this.#afterFade;
      this.#afterFade = null;
      if (kept) void this.#turn(kept);
    };
    this.#paginatorTurn(dir).then(done, done);
  }

  #showPage() {
    if (!this.#awaitingPage) return;
    this.#awaitingPage = false;
    this.#fade(1, FADE_IN_MS);
  }

  #fade(to: 0 | 1, ms: number) {
    const el = this.paginator;
    if (typeof el.animate !== "function") return;
    this.#fadeAnimation?.cancel();
    // What lies under a fading page is the reader's background, not the
    // slide's other sheet.
    if (to === 0) this.#slide?.conceal();
    const animation = el.animate([{ opacity: to ? 0 : 1 }, { opacity: to }], {
      duration: ms,
      easing: "ease-out",
      fill: "forwards",
    });
    this.#fadeAnimation = animation;
    if (to === 0) return;
    // Faded in: drop the animation, the element's own opacity is 1.
    animation.onfinish = () => {
      animation.cancel();
      if (this.#fadeAnimation === animation) this.#fadeAnimation = null;
      this.#slide?.reveal();
    };
  }

  /** Drop a fade in progress — and the turn behind it, if it has not
   *  reached the paginator yet. The page is fully visible afterwards. */
  #cancelFade() {
    this.#fadeGeneration++;
    if (this.#fadeTimer != null) clearTimeout(this.#fadeTimer);
    this.#fadeTimer = null;
    this.#fadeAnimation?.cancel();
    this.#fadeAnimation = null;
    this.#awaitingPage = false;
    this.#turning = false;
    this.#queuedTurn = null;
    this.#afterFade = null;
    this.#slide?.reveal();
  }

  /** Abandon a page turn in progress, faded or sliding. */
  #cancelTurn() {
    this.#cancelFade();
    this.#slide?.cancel();
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
    // A forced writing mode outranks the book's declared progression:
    // vertical-rl columns run right to left, horizontal CJK left to right
    // — also in a book whose spine says rtl because it was set vertically.
    const forced = this.forcedWritingMode();
    if (forced) return forced === "vertical";
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
    if (mode !== this.pageTurn) this.#cancelTurn();
    this.pageTurn = mode;
    this.#applyPageTurn();
  }

  /** The page-turn mode in force. The slide moves whole pages over one
   *  another, so it applies to every section alike — vertical text and a
   *  section laid out against the book's direction included. */
  effectivePageTurn(): PageTurnMode {
    return this.pageTurn;
  }

  /** Build the slide's further renderings when the mode asks for them,
   *  and take them down when it does not: the other modes pay nothing. */
  #applyPageTurn() {
    const book = this.book;
    const wanted =
      this.pageTurn === "slide" &&
      !!book &&
      book.rendition?.layout !== "pre-paginated";
    if (!wanted) {
      this.#dropSlide();
      return;
    }
    if (this.#slide) return;
    // The slide ends a turn itself; the paginator's 100ms pause after
    // each one would drop the turn that follows a skipped slide.
    this.paginator.setAttribute("no-turn-lock", "");
    const slide = new CoverSlide({
      container: this.#container,
      live: this.paginator,
      book,
      styles: () => this.#composedStyles(),
      leftward: () => this.advancesLeftward(),
      reducedMotion: prefersReducedMotion,
      turnLive: (dir) => this.#paginatorTurn(dir),
      request: (dir) => void this.#turn(dir),
      fallback: (dir) => void this.#fadeTurn(dir),
      visible: () => this.lastLocation?.range ?? null,
      onload: (detail, ghost) => this.#onGhostLoad(detail, ghost),
      onoverlayer: ({ doc, index, attach }, ghost) => {
        const overlayer = new Overlayer();
        attach(overlayer);
        this.#handlers.onghostoverlayer?.({ doc, index, overlayer }, ghost);
      },
      ongone: (ghost) => this.#handlers.onghostoverlayer?.(null, ghost),
    });
    slide.setBackground(this.#pageColor);
    this.#slide = slide;
    // Already reading: a ghost goes to the neighbour of this page.
    if (this.lastLocation) slide.sync();
  }

  #dropSlide() {
    const slide = this.#slide;
    if (!slide) return;
    this.#slide = null;
    slide.destroy();
    this.paginator.removeAttribute("no-turn-lock");
    this.#handlers.onghostoverlayer?.(null);
  }

  /** One of the slide's ghost paginators, when there is any — the one
   *  in the turn under way, else the one on the page ahead. For probes
   *  and tests, like the handles after it; nothing in the reader reads
   *  positions from a ghost. */
  get ghost(): PaginatorElement | null {
    return this.#slide?.ghost ?? null;
  }

  /** The section and visible text that ghost last settled on. */
  get ghostLocation(): { index: number; range: Range | null } | null {
    return this.#slide?.shown ?? null;
  }

  /** Every ghost there is: one in the middle of a chapter, more near a
   *  chapter boundary. */
  get ghosts(): PaginatorElement[] {
    return this.#slide?.ghosts ?? [];
  }

  /** The ghost holding the page one turn back (−1) or forward (1). */
  ghostFor(dir: 1 | -1): PaginatorElement | null {
    return this.#slide?.ghostFor(dir) ?? null;
  }

  /** What became of the slide's last turns, and the sections loaded
   *  into its ghosts. */
  get slideLog(): SlideEvent[] {
    return this.#slide?.log ?? [];
  }

  /** The page's own colour. In the slide mode it backs both renderings,
   *  so a sheet hides the one under it whatever the book's CSS leaves
   *  transparent. */
  setPageColor(color: string) {
    this.#pageColor = color;
    this.#slide?.setBackground(color);
  }

  /** The slide following the finger: the gesture layer reports each
   *  move (previous − current, px along the screen's x axis)… */
  dragBy(dx: number): boolean {
    if (this.effectivePageTurn() !== "slide") return false;
    // (While a fallback fade has the page the finger is only kept track
    // of: a sheet joins it once the fade is over.)
    return this.#slide?.dragBy(dx, this.#fading()) ?? false;
  }

  /** …and the release, with its velocity (px/ms). False when the slide
   *  did not have the gesture, had no page to pull toward, or a fade was
   *  in its way: it is a plain threshold swipe then. */
  dragEnd(vx: number): boolean {
    return this.#slide?.dragEnd(vx) ?? false;
  }

  /** The touch was cancelled, or another began. */
  dragCancel() {
    this.#slide?.dragCancel();
  }

  /** CSS injected into every section. A pair is [before, after]: `before`
   *  is prepended to <head> (the book's own styles win), `after` appended
   *  (ours win at equal specificity). The forced writing mode, when there
   *  is one, rides at the end of `after`. */
  setStyles(styles: string | [string, string]) {
    this.#styles = styles;
    const composed = this.#composedStyles();
    this.paginator.setStyles(composed);
    this.#slide?.setStyles(composed);
  }

  #composedStyles(): string | [string, string] {
    const forced = this.forcedWritingMode();
    const [before, after] = Array.isArray(this.#styles)
      ? this.#styles
      : ["", this.#styles];
    return [before, after + PLATE_CSS + (forced ? writingModeCss(forced) : "")];
  }

  /** The writing mode in force, or null when the book's own stands: no
   *  override asked for, or a fixed-layout book, whose pages are drawn
   *  rather than set. */
  forcedWritingMode(): Exclude<WritingMode, "auto"> | null {
    if (this.writingMode === "auto") return null;
    if (this.book?.rendition?.layout === "pre-paginated") return null;
    return this.writingMode;
  }

  /** Whether choosing a writing direction makes sense for this book: a
   *  Chinese, Japanese or Korean one by its declared language, or one
   *  whose own text runs vertically (a mislabelled language is common). */
  offersWritingMode(): boolean {
    if (this.book?.rendition?.layout === "pre-paginated") return false;
    return !!this.#language.isCJK || this.#nativeVertical;
  }

  /**
   * Force the book horizontal or vertical, or hand it back to its own
   * styles ("auto"). The paginator reads a section's writing mode once,
   * when it loads it, so the section on screen is loaded again — at
   * `anchor` (a CFI; the start of the visible text when omitted), which
   * the new layout re-derives its page from. Resolves to whether a
   * section was laid out again; before the first render the mode is only
   * recorded.
   */
  async setWritingMode(mode: WritingMode, anchor?: string): Promise<boolean> {
    if (mode === this.writingMode) return false;
    const before = this.forcedWritingMode();
    this.writingMode = mode;
    const index = this.currentIndex();
    if (index == null) {
      this.paginator.setStyles(this.#composedStyles());
      return false;
    }
    if (this.forcedWritingMode() === before) return false;
    const cfi = anchor || this.lastLocation?.startCfi;
    const target = cfi ? this.resolve(cfi) : null;
    this.#cancelTurn();
    // The ghosts read their sections' writing mode at load too: fresh
    // ones follow the page the reload lands on.
    this.#slide?.reset();
    await this.paginator.reload(
      target?.index === index && target.anchor != null
        ? withTextStart(target).anchor
        : (this.lastLocation?.fraction ?? 0),
      this.#composedStyles(),
    );
    return true;
  }

  /** Declare layout parameters. Only changed values are written, so a
   *  re-declaration of the same layout triggers no re-render. */
  setLayout(params: LayoutParams) {
    this.#writeLayout(this.paginator, params);
  }

  /** The same declaration for the slide's ghosts. A ghost's section may
   *  be written the other way from the one on screen (a horizontal plate
   *  in a vertical book), so each gets the layout for its own section's
   *  writing mode — see `onghostload`. */
  setGhostLayout(layoutFor: (vertical: boolean) => LayoutParams) {
    for (const ghost of this.#slide?.ghosts ?? [])
      this.#writeLayout(
        ghost,
        layoutFor(this.#ghostVertical.get(ghost) ?? this.vertical),
      );
  }

  #writeLayout(paginator: PaginatorElement, params: LayoutParams) {
    for (const key of Object.keys(params) as (keyof LayoutParams)[]) {
      const value = params[key];
      if (value == null) continue;
      const attr = ATTR_FOR[key];
      const next = attrValue(key, value);
      if (paginator.getAttribute(attr) !== next) {
        paginator.setAttribute(attr, next);
      }
    }
  }

  /** The point CFI at the start of a range CFI (a point CFI is returned
   *  as-is). */
  collapseCFI(cfi: string): string {
    try {
      return CFI.collapse(normalizeCFI(cfi));
    } catch {
      return cfi;
    }
  }

  cfiOf(index: number, range: Range | null): string {
    const base = this.book?.sections[index]?.cfi ?? CFI.fake.fromIndex(index);
    if (!range) return base;
    return CFI.joinIndir(base, cfiFromRange(range));
  }

  /** The reading position a range stands for: the point CFI of where its
   *  text starts (see textStart) — what a relocation reports as
   *  `startCfi` and progress saves store. */
  positionCFI(index: number, range: Range): string {
    return this.cfiOf(index, textStart(range));
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
    this.#cancelFade();
    this.#dropSlide();
    try {
      this.paginator.destroy();
    } catch {
      // destroy() before the first section loaded has no view to tear down
    }
    this.paginator.remove();
    this.#pristineDocs.clear();
    this.#prefetch?.destroy();
    this.#prefetch = null;
    this.book?.destroy?.();
    this.book = null;
  }

  /**
   * What every rendered copy of a section gets before it is laid out —
   * the live one and the slide's ghost alike, so the two read the same:
   * language and direction where the document names none, the direction
   * a forced writing mode needs, upright numbers, illustration plates.
   * Returns the section's writing mode and direction as the paginator
   * is about to read them.
   */
  #prepareSection(doc: Document): { vertical: boolean; rtl: boolean } {
    const root = doc.documentElement;
    root.lang ||= this.#language.canonical ?? "";
    if (!this.#language.isCJK) root.dir ||= this.#language.direction ?? "";
    if (this.forcedWritingMode()) {
      // The paginator also reads the dir attributes, which no injected
      // rule can outrank; the rendered copy is ours to adjust.
      if (root.dir === "rtl") root.dir = "ltr";
      if (doc.body.dir === "rtl") doc.body.dir = "ltr";
    }
    const style = doc.defaultView?.getComputedStyle(doc.body);
    const writingMode = style?.writingMode;
    const vertical = !!writingMode && writingMode.startsWith("vertical");
    // Mirrors the paginator's own getDirection() — read here because the
    // load event precedes the render that stamps the paginator's `dir`.
    const rtl = doc.body.dir === "rtl" || style?.direction === "rtl";
    if (this.forcedWritingMode() === "vertical") this.#combineNumbers(doc);
    if (vertical) markPlates(doc);
    return { vertical, rtl };
  }

  #onLoad({ doc, index }: { doc: Document; index: number }) {
    const { vertical, rtl } = this.#prepareSection(doc);
    this.vertical = vertical;
    this.sectionRtl = rtl;
    // What a forced layout shows says nothing about the book itself.
    if (!this.forcedWritingMode()) {
      if (this.vertical || this.sectionRtl) this.#inferredLeftward = true;
      if (this.vertical) this.#nativeVertical = true;
    }
    this.#handleLinks(doc, index);
    this.#handlers.onload?.({ doc, index });
  }

  /** A section for one of the slide's ghosts: the same adjustments,
   *  none of the reader's state (the writing mode on screen, the inferred
   *  direction) and none of its listeners. */
  #onGhostLoad(
    { doc, index }: { doc: Document; index: number },
    ghost: PaginatorElement,
  ) {
    const { vertical } = this.#prepareSection(doc);
    this.#ghostVertical.set(ghost, vertical);
    this.#handlers.onghostload?.({ doc, index, vertical });
  }

  /**
   * A book forced vertical has its short numbers stood upright (tcy.ts)
   * — only text the force turned. Text the book itself sets vertically
   * (the whole body, or an inner container) comes with the publisher's
   * own markup and is left as written, as is anything the book already
   * combines or sets upright. The section's own writing mode is read
   * with the forced rules standing down for the moment; this runs at
   * load, before the first layout.
   */
  #combineNumbers(doc: Document) {
    const win = doc.defaultView;
    const root = doc.documentElement;
    if (!win) return;
    root.setAttribute(OWN_LAYOUT_ATTR, "");
    try {
      combineShortNumbers(doc, (parent) => {
        const style = win.getComputedStyle(parent);
        const combine =
          style.getPropertyValue("text-combine-upright") ||
          style.getPropertyValue("-webkit-text-combine");
        const orientation = style.getPropertyValue("text-orientation");
        return (
          !style.writingMode.startsWith("vertical") &&
          !style.writingMode.startsWith("sideways") &&
          (!combine || combine === "none") &&
          (!orientation || orientation === "mixed")
        );
      });
    } catch (e) {
      console.error(e);
    } finally {
      root.removeAttribute(OWN_LAYOUT_ATTR);
    }
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
      startCfi: range ? this.positionCFI(detail.index, range) : cfi,
    };
    this.lastLocation = location;
    this.#showPage();
    this.#slide?.relocated();
    if (detail.index !== this.#prefetchIndex) {
      this.#prefetchIndex = detail.index;
      this.#prefetch?.around(detail.index);
    }
    this.#handlers.onrelocate?.(location);
  }
}
