/**
 * The scroll strip — PROTOTYPE (reached with ?turn=scroll).
 *
 * Chapters stand one after another on a long canvas which the browser
 * scrolls natively. Each chapter is one iframe as tall as its text.
 *
 * The one rule of the layout: the chapter under the reading line (the
 * top of the screen) keeps its place on the canvas. The chapters before
 * it are stacked upward from its top, the chapters after it downward
 * from its bottom. So a chapter joining or leaving either end, or one
 * changing height elsewhere, never moves the text being read, and the
 * scroll position is not touched for it.
 *
 * The scroll position is written in two places only: when the strip is
 * opened on a destination, and when the whole canvas is shifted at rest
 * (#rebase) — the book's first chapter has to sit at the canvas's top
 * for the browser to stop there.
 *
 * Not here yet: vertical text (everything is set horizontally), saved
 * progress, highlights, selection menu, links, keys.
 */
import type { Book, NavTarget } from "./core";

export interface StripOptions {
  container: HTMLElement;
  book: Book;
  styles: () => string | [string, string];
  /** Per-section DOM preparation shared with the paginator's sections. */
  prepare: (doc: Document) => void;
  /** Left/right gutter and the space above and below a chapter, px. */
  gutter: number;
  spacing: number;
  /** Longest line, px. */
  measure: number;
  background: string;
  ontap?: () => void;
}

export interface StripLogEntry {
  at: number;
  what: string;
  index?: number;
  ms?: number;
}

/** Where the opened chapter is put when chapters may yet come before
 *  it: far enough down that they have room to be stacked upward. */
const ORIGIN = 2_000_000;
/** The canvas is shifted back when the first chapter comes this near
 *  its top without being the book's first. */
const ORIGIN_LOW = 200_000;
/** Text kept ready beyond the screen, in screens, each way. */
const AHEAD = 2;
/** A chapter at either end is let go when it is this many screens away. */
const LET_GO = 5;
/** How long a chapter may wait for its pictures before it joins. */
const SETTLE_MS = 3000;
/** No scroll and no finger for this long: the strip is at rest. */
const REST_MS = 200;
const RETRY_MS = 5000;

interface Chapter {
  index: number;
  frame: HTMLDivElement;
  doc: Document;
  top: number;
  height: number;
  observer: ResizeObserver;
  unload: () => void;
}

export class ScrollStrip {
  #o: StripOptions;
  #scroller: HTMLDivElement;
  #canvas: HTMLDivElement;
  #readout: HTMLDivElement;
  /** The mounted chapters, in reading order, with no gap between them. */
  #chapters: Chapter[] = [];
  #pinned: Chapter | null = null;
  #loading: Record<1 | -1, boolean> = { 1: false, [-1]: false };
  #retryAt: Record<1 | -1, number> = { 1: 0, [-1]: 0 };
  #generation = 0;
  #touches = 0;
  #frameAsked = false;
  #restTimer: ReturnType<typeof setTimeout> | null = null;
  #destroyed = false;
  log: StripLogEntry[] = [];

  constructor(options: StripOptions) {
    this.#o = options;
    const scroller = document.createElement("div");
    scroller.dataset.testid = "scroll-strip";
    Object.assign(scroller.style, {
      position: "absolute",
      inset: "0",
      overflowX: "hidden",
      overflowY: "auto",
      // The layout keeps the read chapter in place itself; a browser
      // that also anchors would move it twice.
      overflowAnchor: "none",
      background: options.background,
    });
    const canvas = document.createElement("div");
    Object.assign(canvas.style, { position: "relative", width: "100%" });
    scroller.append(canvas);
    const readout = document.createElement("div");
    readout.dataset.testid = "scroll-strip-readout";
    Object.assign(readout.style, {
      position: "absolute",
      left: "8px",
      bottom: "calc(8px + env(safe-area-inset-bottom, 0px))",
      zIndex: "5",
      padding: "2px 6px",
      borderRadius: "6px",
      font: "11px/1.4 ui-monospace, monospace",
      color: "#fff",
      background: "rgba(0,0,0,.55)",
      pointerEvents: "none",
      whiteSpace: "pre",
    });
    options.container.append(scroller, readout);
    this.#scroller = scroller;
    this.#canvas = canvas;
    this.#readout = readout;
    scroller.addEventListener("scroll", () => this.#scrolled(), {
      passive: true,
    });
    this.#watchTouches(scroller);
  }

  get scroller(): HTMLElement {
    return this.#scroller;
  }

  /** The mounted chapters as the layout has them (debug). */
  get chapters(): { index: number; top: number; height: number }[] {
    return this.#chapters.map(({ index, top, height }) => ({
      index,
      top,
      height,
    }));
  }

  get pinnedIndex(): number | null {
    return this.#pinned?.index ?? null;
  }

  /** Throw the strip away and build it around `target`. */
  async open(target: Pick<NavTarget, "index" | "anchor">): Promise<void> {
    const generation = ++this.#generation;
    for (const chapter of this.#chapters) this.#discard(chapter);
    this.#chapters = [];
    this.#pinned = null;
    this.#loading = { 1: false, [-1]: false };
    const chapter = await this.#build(target.index, generation);
    if (!chapter) return;
    chapter.top = this.#adjacent(target.index, -1) == null ? 0 : ORIGIN;
    this.#chapters = [chapter];
    this.#pinned = chapter;
    this.#layout();
    chapter.frame.style.visibility = "";
    this.#scroller.scrollTop =
      chapter.top + this.#offsetOf(chapter, target.anchor);
    this.#fill();
    this.#report();
  }

  destroy() {
    this.#destroyed = true;
    this.#generation++;
    if (this.#restTimer) clearTimeout(this.#restTimer);
    for (const chapter of this.#chapters) this.#discard(chapter);
    this.#chapters = [];
    this.#scroller.remove();
    this.#readout.remove();
  }

  #offsetOf(chapter: Chapter, anchor: NavTarget["anchor"]): number {
    let at: unknown = anchor;
    try {
      if (typeof anchor === "function") at = anchor(chapter.doc);
    } catch {
      return 0;
    }
    if (typeof at === "number") return at * chapter.height;
    const rects = (
      at as { getClientRects?: () => DOMRectList } | null
    )?.getClientRects?.();
    if (!rects?.length) return 0;
    const rect = Array.from(rects).find((r) => r.height > 0) ?? rects[0];
    // The iframe is as tall as its document and never scrolls: a rect's
    // top in it is the distance from the chapter's top.
    return Math.max(0, rect.top);
  }

  #adjacent(index: number, dir: 1 | -1): number | null {
    const { sections } = this.#o.book;
    for (let i = index + dir; i >= 0 && i < sections.length; i += dir)
      if (sections[i].linear !== "no") return i;
    return null;
  }

  #layoutCss(): string {
    const { gutter, spacing, measure } = this.#o;
    const screen = this.#scroller.clientHeight;
    return `html {
  box-sizing: border-box !important;
  writing-mode: horizontal-tb !important;
  width: auto !important;
  height: auto !important;
  min-height: 0 !important;
  column-width: auto !important;
  margin: 0 !important;
  padding: ${spacing}px ${gutter}px !important;
  overflow: hidden !important;
}
body {
  writing-mode: horizontal-tb !important;
  max-width: ${measure}px !important;
  height: auto !important;
  min-height: 0 !important;
  margin: 0 auto !important;
}
img, svg, video {
  max-width: 100% !important;
  max-height: ${Math.round(screen * 0.9)}px !important;
  object-fit: contain;
  box-sizing: border-box;
}`;
  }

  /** Load a chapter and wait until its height will not change under the
   *  reader: pictures sized, fonts in. It is not on the strip yet. */
  async #build(index: number, generation: number): Promise<Chapter | null> {
    const section = this.#o.book.sections[index];
    const started = performance.now();
    const src = await section.load();
    const stale = () => generation !== this.#generation || this.#destroyed;
    if (stale()) {
      section.unload();
      return null;
    }
    const frame = document.createElement("div");
    Object.assign(frame.style, {
      position: "absolute",
      left: "0",
      top: "0",
      width: "100%",
      visibility: "hidden",
    });
    frame.dataset.index = String(index);
    const iframe = document.createElement("iframe");
    iframe.setAttribute("sandbox", "allow-same-origin");
    iframe.setAttribute("scrolling", "no");
    Object.assign(iframe.style, {
      display: "block",
      width: "100%",
      height: "0",
      border: "0",
    });
    frame.append(iframe);
    this.#canvas.append(frame);
    await new Promise<void>((resolve) => {
      iframe.addEventListener("load", () => resolve(), { once: true });
      iframe.src = src;
    });
    const doc = iframe.contentDocument;
    if (stale() || !doc?.body) {
      frame.remove();
      section.unload();
      return null;
    }
    const laidOut = performance.now();
    const styles = this.#o.styles();
    const [before, after] = Array.isArray(styles) ? styles : ["", styles];
    const first = doc.createElement("style");
    first.textContent = before;
    doc.head.prepend(first);
    const last = doc.createElement("style");
    last.textContent = after + this.#layoutCss();
    doc.head.append(last);
    this.#o.prepare(doc);
    this.#watchTouches(doc);
    doc.addEventListener("click", (e) => {
      if ((e.target as Element | null)?.closest?.("a[href]")) {
        e.preventDefault();
        return;
      }
      if (!doc.getSelection()?.isCollapsed) return;
      this.#o.ontap?.();
    });
    const work = performance.now() - laidOut;
    await Promise.race([
      Promise.all([
        ...Array.from(doc.images, (img) =>
          img.complete ? null : img.decode().catch(() => null),
        ),
        doc.fonts?.ready,
      ]),
      new Promise((resolve) => setTimeout(resolve, SETTLE_MS)),
    ]);
    if (stale()) {
      frame.remove();
      section.unload();
      return null;
    }
    const chapter: Chapter = {
      index,
      frame,
      doc,
      top: 0,
      height: 0,
      observer: null as unknown as ResizeObserver,
      unload: () => section.unload(),
    };
    const measure = () => {
      const height = Math.ceil(
        doc.documentElement.getBoundingClientRect().height,
      );
      if (height === chapter.height) return false;
      chapter.height = height;
      iframe.style.height = `${height}px`;
      return true;
    };
    measure();
    // The document's own window makes the observer: its callback then
    // runs in the frame the text was laid out in, before it is painted.
    const Observer = doc.defaultView?.ResizeObserver ?? ResizeObserver;
    chapter.observer = new Observer(() => {
      if (!measure() || !this.#chapters.includes(chapter)) return;
      this.#note("resized", index);
      this.#layout();
    });
    chapter.observer.observe(doc.documentElement);
    this.#note("built", index, performance.now() - started);
    this.#note("styled", index, work);
    return chapter;
  }

  #discard(chapter: Chapter) {
    chapter.observer.disconnect();
    chapter.frame.remove();
    chapter.unload();
  }

  /** Place every chapter from the pinned one outward. */
  #layout() {
    const chapters = this.#chapters;
    const pinned = this.#pinned;
    if (!pinned || !chapters.length) return;
    const at = chapters.indexOf(pinned);
    for (let i = at + 1; i < chapters.length; i++)
      chapters[i].top = chapters[i - 1].top + chapters[i - 1].height;
    for (let i = at - 1; i >= 0; i--)
      chapters[i].top = chapters[i + 1].top - chapters[i].height;
    for (const chapter of chapters)
      chapter.frame.style.top = `${chapter.top}px`;
    const last = chapters[chapters.length - 1];
    // One blank screen after the last chapter mounted while more are to
    // come: the bare paper a chapter not yet here is waited for on.
    const more = this.#adjacent(last.index, 1) != null;
    this.#canvas.style.height = `${
      last.top + last.height + (more ? this.#scroller.clientHeight : 0)
    }px`;
  }

  #scrolled() {
    if (this.#restTimer) clearTimeout(this.#restTimer);
    this.#restTimer = setTimeout(() => this.#rested(), REST_MS);
    if (this.#frameAsked) return;
    this.#frameAsked = true;
    requestAnimationFrame(() => {
      this.#frameAsked = false;
      if (this.#destroyed) return;
      this.#pin();
      this.#fill();
      this.#report();
    });
  }

  /** The chapter under the reading line becomes the one that stays. */
  #pin() {
    const line = this.#scroller.scrollTop + 1;
    const chapters = this.#chapters;
    if (!chapters.length) return;
    let pinned = chapters[0];
    for (const chapter of chapters) if (chapter.top <= line) pinned = chapter;
    this.#pinned = pinned;
  }

  /** Keep AHEAD screens of text mounted each way; let go of what is far. */
  #fill() {
    const chapters = this.#chapters;
    if (!chapters.length) return;
    const screen = this.#scroller.clientHeight;
    const top = this.#scroller.scrollTop;
    const bottom = top + screen;
    const first = chapters[0];
    const last = chapters[chapters.length - 1];
    if (last.top + last.height - bottom < AHEAD * screen) this.#extend(1);
    if (top - first.top < AHEAD * screen) this.#extend(-1);
    if (chapters.length < 2) return;
    let changed = false;
    if (
      first !== this.#pinned &&
      top - (first.top + first.height) > LET_GO * screen
    ) {
      chapters.shift();
      this.#discard(first);
      this.#note("let go", first.index);
      changed = true;
    }
    if (last !== this.#pinned && last.top - bottom > LET_GO * screen) {
      chapters.pop();
      this.#discard(last);
      this.#note("let go", last.index);
      changed = true;
    }
    if (changed) this.#layout();
  }

  #extend(dir: 1 | -1) {
    if (this.#loading[dir] || performance.now() < this.#retryAt[dir]) return;
    const chapters = this.#chapters;
    const edge = dir > 0 ? chapters[chapters.length - 1] : chapters[0];
    const index = this.#adjacent(edge.index, dir);
    if (index == null) return;
    const generation = this.#generation;
    this.#loading[dir] = true;
    this.#build(index, generation)
      .then((chapter) => {
        if (generation !== this.#generation) {
          if (chapter) this.#discard(chapter);
          return;
        }
        this.#loading[dir] = false;
        if (!chapter) return;
        // Still the neighbour of the end it was built for?
        const now = this.#chapters;
        const end = dir > 0 ? now[now.length - 1] : now[0];
        if (!end || this.#adjacent(end.index, dir) !== index) {
          this.#discard(chapter);
          return;
        }
        if (dir > 0) now.push(chapter);
        else now.unshift(chapter);
        this.#layout();
        chapter.frame.style.visibility = "";
        this.#note("joined", index);
        this.#fill();
        this.#report();
      })
      .catch((e: unknown) => {
        if (generation !== this.#generation) return;
        console.warn(e);
        this.#loading[dir] = false;
        this.#retryAt[dir] = performance.now() + RETRY_MS;
        this.#note("failed", index);
        this.#report();
      });
  }

  #watchTouches(target: Document | HTMLElement) {
    const down = () => (this.#touches += 1);
    const up = () => {
      this.#touches = Math.max(0, this.#touches - 1);
      if (!this.#touches) this.#scrolled();
    };
    target.addEventListener("touchstart", down, { passive: true });
    target.addEventListener("touchend", up, { passive: true });
    target.addEventListener("touchcancel", up, { passive: true });
  }

  #rested() {
    if (this.#destroyed || this.#touches) return;
    const first = this.#chapters[0];
    if (!first) return;
    const start = this.#adjacent(first.index, -1) == null;
    if (start && first.top !== 0) this.#rebase(-first.top);
    else if (!start && first.top < ORIGIN_LOW) this.#rebase(ORIGIN);
  }

  /** Shift the whole canvas, and the scroll position with it, in one
   *  frame: nothing moves on screen. */
  #rebase(delta: number) {
    const top = this.#scroller.scrollTop;
    for (const chapter of this.#chapters) chapter.top += delta;
    this.#layout();
    this.#scroller.scrollTop = top + delta;
    this.#note(`rebased ${delta}`);
  }

  #note(what: string, index?: number, ms?: number) {
    this.log.push({ at: Math.round(performance.now()), what, index, ms });
    if (this.log.length > 200) this.log.shift();
  }

  #report() {
    const chapters = this.#chapters;
    const pinned = this.#pinned;
    if (!pinned || !chapters.length) return;
    const into = this.#scroller.scrollTop - pinned.top;
    const percent = Math.max(
      0,
      Math.min(100, Math.round((into / Math.max(1, pinned.height)) * 100)),
    );
    const built = [...this.log].reverse().find((l) => l.what === "built");
    const styled = [...this.log].reverse().find((l) => l.what === "styled");
    this.#readout.textContent =
      `章 ${pinned.index} · ${percent}% · 掛著 ${chapters[0].index}–${
        chapters[chapters.length - 1].index
      }` +
      (built
        ? `\n上次掛章 ${built.index}: ${Math.round(built.ms ?? 0)}ms(其中排版 ${Math.round(
            styled?.ms ?? 0,
          )}ms)`
        : "");
  }
}
