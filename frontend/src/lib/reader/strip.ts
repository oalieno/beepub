/**
 * The scroll strip — the renderer of the "scroll" page-turn mode.
 *
 * Chapters stand one after another on a long canvas which the browser
 * scrolls natively. Each chapter is one iframe as large as its text.
 *
 * The one rule of the layout: the chapter under the reading line (the
 * leading edge of the screen) keeps its place on the canvas. The
 * chapters before it are stacked backward from its start, the chapters
 * after it forward from its end. So a chapter joining or leaving either
 * end, or one changing size elsewhere, never moves the text being read,
 * and the scroll position is not touched for it.
 *
 * The scroll position is written for these only: a destination (the
 * strip opened on one, a jump within what is mounted, a screen's move by
 * key), a wheel followed along a leftward strip, and the whole canvas
 * shifted at rest (#rebase) — the book's first chapter has to sit at the
 * canvas's start for the browser to stop there.
 *
 * A horizontal book's strip runs downward, a vertical book's leftward
 * (an rtl scroller: the position along it is -scrollLeft). The chapter
 * the strip is opened on decides, and every chapter is set that way. A
 * chapter's `top` and `height` below are its start and its extent ALONG
 * the strip, whichever way that runs.
 *
 * Where the reader is, is told through `onrelocate` — not for every
 * frame of a scroll: when the strip comes to rest, and when the reading
 * line passes into another chapter. A report says the chapter, how far
 * into it the line is, and the text on screen from the line on; one that
 * would say what the last one said is not made.
 *
 * Not here yet: highlights, the selection menu, footnotes (slice ②); a
 * chapter that fails to load says nothing (slice ③).
 */
import type { Book, NavTarget } from "./core";
import { getVisibleRange } from "./vendor/foliate/paginator.js";

export interface StripLayout {
  /** The reader's left/right and top/bottom margins, px. */
  marginX: number;
  marginY: number;
  /** Longest line, px: of horizontal text, and of vertical text. */
  measure: number;
  verticalMeasure: number;
}

export interface StripRelocation {
  /** "scroll" (the reader moved) · "navigation" | "anchor" (ours). */
  reason: string;
  index: number;
  /** How far into the chapter the reading line is, 0..1. */
  fraction: number;
  /** The chapter's text on screen, from the reading line on. */
  range: Range | null;
}

export interface StripOptions {
  container: HTMLElement;
  book: Book;
  styles: () => string | [string, string];
  layout: () => StripLayout;
  background: string;
  reducedMotion: () => boolean;
  /** A chapter's document, styled and set the strip's way, before it is
   *  measured. `ownVertical`: the book itself (or a forced writing mode)
   *  runs this chapter's text vertically. */
  onload: (detail: {
    doc: Document;
    index: number;
    ownVertical: boolean;
  }) => void;
  onrelocate: (detail: StripRelocation) => void;
}

export interface StripLogEntry {
  at: number;
  what: string;
  index?: number;
  ms?: number;
}

type Anchor = NavTarget["anchor"];

/** Where the opened chapter is put when chapters may yet come before
 *  it: far enough along that they have room to be stacked backward. */
const ORIGIN = 2_000_000;
/** The canvas is shifted back when the first chapter comes this near
 *  its start without being the book's first. */
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
/** A chapter on its way is not announced before this: a spinner that
 *  comes and goes at once is worse than the bare paper. */
const SPINNER_AFTER_MS = 400;
/** How quickly the glide's spring closes on its target, 1/s. */
const GLIDE_STIFFNESS = 8;
/** A key moves the strip by this much of a screen: the last lines read
 *  stay in sight as the first of the next. */
const PAGE_STEP = 0.9;
/** The reading line stands this far inside the screen's leading edge: a
 *  line of which only a sliver is left there (the scroller keeps whole
 *  pixels, text does not) is not the line being read. */
const LINE_INSET = 2;

interface Chapter {
  index: number;
  frame: HTMLDivElement;
  doc: Document;
  /** Set the strip's way at build — the axis it was measured along. */
  vertical: boolean;
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
  #vertical = false;
  #loading: Record<1 | -1, boolean> = { 1: false, [-1]: false };
  #retryAt: Record<1 | -1, number> = { 1: 0, [-1]: 0 };
  #generation = 0;
  #touches = 0;
  #frameAsked = false;
  #restTimer: ReturnType<typeof setTimeout> | null = null;
  #destroyed = false;
  /** One spinner for each end of the strip, on the bare paper there. */
  #spinners: Record<1 | -1, HTMLDivElement>;
  #spinnerTimers: Record<1 | -1, ReturnType<typeof setTimeout> | null> = {
    1: null,
    [-1]: null,
  };
  #extent = 0;
  #glideTarget: number | null = null;
  #glideFrame = 0;
  /** The spring's own position (the scroller rounds what it is given),
   *  its speed in px/s and the time of its last step. */
  #glideAt = 0;
  #glideSpeed = 0;
  #glideTime = 0;
  /** What the last report said: the chapter, and how far into it. */
  #told: { index: number; offset: number } | null = null;
  log: StripLogEntry[] = [];

  constructor(options: StripOptions) {
    this.#o = options;
    const scroller = document.createElement("div");
    scroller.dataset.testid = "scroll-strip";
    Object.assign(scroller.style, {
      position: "absolute",
      inset: "0",
      // The layout keeps the read chapter in place itself; a browser
      // that also anchors would move it twice.
      overflowAnchor: "none",
      background: options.background,
    });
    const canvas = document.createElement("div");
    canvas.style.position = "relative";
    scroller.append(canvas);
    const spinner = () => {
      const el = document.createElement("div");
      el.dataset.testid = "scroll-strip-pending";
      Object.assign(el.style, {
        position: "absolute",
        width: "20px",
        height: "20px",
        margin: "-10px",
        borderRadius: "50%",
        border: "2px solid rgba(128,128,128,.25)",
        borderTopColor: "rgba(128,128,128,.9)",
        display: "none",
      });
      el.animate(
        [{ transform: "rotate(0)" }, { transform: "rotate(360deg)" }],
        {
          duration: 800,
          iterations: Infinity,
        },
      );
      canvas.append(el);
      return el;
    };
    this.#spinners = { 1: spinner(), [-1]: spinner() };
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
    this.#watchWheel(scroller);
    this.#setAxis(false);
  }

  #setAxis(vertical: boolean) {
    this.#vertical = vertical;
    Object.assign(
      this.#scroller.style,
      vertical
        ? { overflowX: "auto", overflowY: "hidden", direction: "rtl" }
        : { overflowX: "hidden", overflowY: "auto", direction: "ltr" },
    );
    Object.assign(
      this.#canvas.style,
      vertical ? { height: "100%", width: "" } : { width: "100%", height: "" },
    );
  }

  /** The screen's extent along the strip. */
  get #screen(): number {
    return this.#vertical
      ? this.#scroller.clientWidth
      : this.#scroller.clientHeight;
  }

  /** How far along the strip the screen's leading edge is. */
  get #at(): number {
    return this.#vertical
      ? Math.abs(this.#scroller.scrollLeft)
      : this.#scroller.scrollTop;
  }

  set #at(value: number) {
    if (this.#vertical) this.#scroller.scrollLeft = -value;
    else this.#scroller.scrollTop = value;
  }

  get vertical(): boolean {
    return this.#vertical;
  }

  get position(): number {
    return this.#at;
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

  /** The chapter under the reading line (null before the first open). */
  get pinnedIndex(): number | null {
    return this.#pinned?.index ?? null;
  }

  /** The mounted chapters' documents, the one being read first. */
  getContents(): { index: number; doc: Document }[] {
    const pinned = this.#pinned;
    const rest = this.#chapters.filter((chapter) => chapter !== pinned);
    return (pinned ? [pinned, ...rest] : rest).map(({ index, doc }) => ({
      index,
      doc,
    }));
  }

  /** The book's last chapter is mounted and its end is on screen. */
  get atEnd(): boolean {
    const last = this.#chapters[this.#chapters.length - 1];
    if (!last || this.#adjacent(last.index, 1) != null) return false;
    return this.#at + this.#screen >= last.top + last.height - 1;
  }

  setBackground(color: string) {
    this.#scroller.style.background = color;
  }

  /** Show `target`: where its chapter is mounted the strip is moved to
   *  it, otherwise it is built anew around it. The place is reported
   *  (as `reason`) before this resolves. */
  async goTo(
    target: Pick<NavTarget, "index" | "anchor">,
    reason = "navigation",
  ): Promise<void> {
    const chapter = this.#chapters.find((c) => c.index === target.index);
    if (!chapter) return this.open(target, reason);
    this.#stopGlide();
    this.#at = chapter.top + this.#offsetOf(chapter, target.anchor);
    this.#pin();
    this.#fill();
    this.#tell(reason, true);
  }

  /** Build the strip anew around `target`. What is on screen stays
   *  until the chapter is ready to take its place. */
  async open(
    target: Pick<NavTarget, "index" | "anchor">,
    reason = "navigation",
  ): Promise<void> {
    const generation = ++this.#generation;
    this.#loading = { 1: false, [-1]: false };
    this.#pending(1, false);
    this.#pending(-1, false);
    const chapter = await this.#build(target.index, generation, true);
    if (!chapter) return;
    this.#stopGlide();
    for (const old of this.#chapters) this.#discard(old);
    this.#setAxis(chapter.vertical);
    chapter.top = this.#adjacent(target.index, -1) == null ? 0 : ORIGIN;
    this.#chapters = [chapter];
    this.#pinned = chapter;
    this.#layout();
    chapter.frame.style.visibility = "";
    this.#at = chapter.top + this.#offsetOf(chapter, target.anchor);
    this.#fill();
    this.#tell(reason, true);
  }

  /** One screen back or forward along the strip. */
  page(dir: 1 | -1) {
    this.#glide(dir * this.#screen * PAGE_STEP);
  }

  destroy() {
    this.#destroyed = true;
    this.#generation++;
    if (this.#restTimer) clearTimeout(this.#restTimer);
    this.#pending(1, false);
    this.#pending(-1, false);
    this.#stopGlide();
    for (const chapter of this.#chapters) this.#discard(chapter);
    this.#chapters = [];
    this.#pinned = null;
    this.#scroller.remove();
    this.#readout.remove();
  }

  /** How far into `chapter` an anchor (a fraction, an element, a range
   *  — or what makes one from the document) stands. */
  #offsetOf(chapter: Chapter, anchor: Anchor): number {
    let at: unknown = anchor;
    try {
      if (typeof anchor === "function") at = anchor(chapter.doc);
    } catch {
      return 0;
    }
    if (typeof at === "number") return Math.floor(at * chapter.height);
    const rect = firstRect(at);
    if (!rect) return 0;
    // The iframe is as large as its document and never scrolls: a rect
    // in it is measured from the chapter's own edges. A line of text is
    // given its leading back (a glyph's box is thinner than its line),
    // so it does not stand hard against the screen's edge. Whole pixels,
    // and never past the line's own edge (see LINE_INSET).
    const edge = this.#vertical ? chapter.height - rect.right : rect.top;
    return Math.max(0, Math.floor(edge - leadOf(at, rect, this.#vertical)));
  }

  #adjacent(index: number, dir: 1 | -1): number | null {
    const { sections } = this.#o.book;
    for (let i = index + dir; i >= 0 && i < sections.length; i += dir)
      if (sections[i].linear !== "no") return i;
    return null;
  }

  #layoutCss(vertical: boolean): string {
    const { marginX, marginY, measure, verticalMeasure } = this.#o.layout();
    const mode = vertical ? "vertical-rl" : "horizontal-tb";
    // Across the lines the chapter is as long as its text; along them it
    // has the screen, less the margins, up to the longest line allowed.
    return `html {
  box-sizing: border-box !important;
  writing-mode: ${mode} !important;
  ${vertical ? "height: 100% !important; width: auto !important;" : "width: auto !important; height: auto !important;"}
  min-width: 0 !important;
  min-height: 0 !important;
  column-width: auto !important;
  margin: 0 !important;
  padding: ${marginY}px ${marginX}px !important;
  overflow: hidden !important;
}
body {
  writing-mode: ${mode} !important;
  ${vertical ? `max-height: ${verticalMeasure}px !important; width: auto !important;` : `max-width: ${measure}px !important; height: auto !important;`}
  min-width: 0 !important;
  min-height: 0 !important;
  margin: auto !important;
}
img, svg, video {
  max-width: ${vertical ? `${Math.round(this.#scroller.clientWidth * 0.9)}px` : "100%"} !important;
  max-height: ${vertical ? "100%" : `${Math.round(this.#scroller.clientHeight * 0.9)}px`} !important;
  object-fit: contain;
  box-sizing: border-box;
}`;
  }

  /** Load a chapter and wait until its size will not change under the
   *  reader: pictures sized, fonts in. It is not on the strip yet.
   *  `decide`: this is the chapter the strip is opened on, and its own
   *  writing mode is the way the strip will run. */
  async #build(
    index: number,
    generation: number,
    decide = false,
  ): Promise<Chapter | null> {
    const section = this.#o.book.sections[index];
    const started = performance.now();
    const src = await section.load();
    const stale = () => generation !== this.#generation || this.#destroyed;
    if (stale()) {
      section.unload();
      return null;
    }
    const frame = document.createElement("div");
    frame.style.position = "absolute";
    frame.style.visibility = "hidden";
    frame.dataset.index = String(index);
    const iframe = document.createElement("iframe");
    iframe.setAttribute("sandbox", "allow-same-origin");
    iframe.setAttribute("scrolling", "no");
    iframe.style.display = "block";
    iframe.style.border = "0";
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
    last.textContent = after;
    doc.head.append(last);
    const mode = doc.defaultView?.getComputedStyle(doc.body).writingMode;
    const ownVertical = !!mode && mode.startsWith("vertical");
    const vertical = decide ? ownVertical : this.#vertical;
    Object.assign(
      frame.style,
      vertical
        ? { top: "0", right: "0", height: "100%" }
        : { top: "0", left: "0", width: "100%" },
    );
    Object.assign(
      iframe.style,
      vertical
        ? { height: "100%", width: "0" }
        : { width: "100%", height: "0" },
    );
    last.textContent += this.#layoutCss(vertical);
    this.#o.onload({ doc, index, ownVertical });
    this.#watchTouches(doc);
    this.#watchWheel(doc);
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
      vertical,
      top: 0,
      height: 0,
      observer: null as unknown as ResizeObserver,
      unload: () => section.unload(),
    };
    const measure = () => {
      const rect = doc.documentElement.getBoundingClientRect();
      const height = Math.ceil(vertical ? rect.width : rect.height);
      if (height === chapter.height) return false;
      chapter.height = height;
      iframe.style[vertical ? "width" : "height"] = `${height}px`;
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
    const side = this.#vertical ? "right" : "top";
    for (const chapter of chapters)
      chapter.frame.style[side] = `${chapter.top}px`;
    const last = chapters[chapters.length - 1];
    // One blank screen after the last chapter mounted while more are to
    // come: the bare paper a chapter not yet here is waited for on.
    const more = this.#adjacent(last.index, 1) != null;
    this.#extent = last.top + last.height + (more ? this.#screen : 0);
    this.#canvas.style[this.#vertical ? "width" : "height"] =
      `${this.#extent}px`;
    // The spinners stand in the middle of the bare paper at either end.
    const half = this.#screen / 2;
    const across = this.#vertical ? "top" : "left";
    for (const dir of [1, -1] as const) {
      const style = this.#spinners[dir].style;
      style[side] =
        `${dir > 0 ? last.top + last.height + half : chapters[0].top - half}px`;
      style[across] = "50%";
    }
  }

  #scrolled() {
    if (this.#restTimer) clearTimeout(this.#restTimer);
    this.#restTimer = setTimeout(() => this.#rested(), REST_MS);
    if (this.#frameAsked) return;
    this.#frameAsked = true;
    requestAnimationFrame(() => {
      this.#frameAsked = false;
      if (this.#destroyed) return;
      const before = this.#pinned;
      this.#pin();
      this.#fill();
      // Into another chapter: its name and the progress follow at once,
      // not at the end of a long scroll.
      if (this.#pinned !== before) this.#tell("scroll");
      this.#readOut();
    });
  }

  /** The chapter under the reading line becomes the one that stays. */
  #pin() {
    const line = this.#at + 1;
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
    const screen = this.#screen;
    const top = this.#at;
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
    this.#pending(dir, true);
    this.#build(index, generation)
      .then((chapter) => {
        if (generation !== this.#generation) {
          if (chapter) this.#discard(chapter);
          return;
        }
        this.#loading[dir] = false;
        this.#pending(dir, false);
        if (!chapter) return;
        // Still the neighbour of the end it was built for, and set the
        // way the strip (opened anew meanwhile, perhaps) now runs?
        const now = this.#chapters;
        const end = dir > 0 ? now[now.length - 1] : now[0];
        if (
          !end ||
          this.#adjacent(end.index, dir) !== index ||
          chapter.vertical !== this.#vertical
        ) {
          this.#discard(chapter);
          return;
        }
        if (dir > 0) now.push(chapter);
        else now.unshift(chapter);
        this.#layout();
        chapter.frame.style.visibility = "";
        this.#note("joined", index);
        this.#fill();
        this.#readOut();
      })
      .catch((e: unknown) => {
        if (generation !== this.#generation) return;
        console.warn(e);
        this.#loading[dir] = false;
        this.#pending(dir, false);
        this.#retryAt[dir] = performance.now() + RETRY_MS;
        this.#note("failed", index);
        this.#readOut();
      });
  }

  /** A chapter is on its way at this end, or no longer. */
  #pending(dir: 1 | -1, on: boolean) {
    const timer = this.#spinnerTimers[dir];
    if (timer) clearTimeout(timer);
    this.#spinnerTimers[dir] = on
      ? setTimeout(
          () => (this.#spinners[dir].style.display = ""),
          SPINNER_AFTER_MS,
        )
      : null;
    if (!on) this.#spinners[dir].style.display = "none";
  }

  #watchTouches(target: Document | HTMLElement) {
    const down = () => {
      this.#touches += 1;
      // The finger has the strip now.
      this.#stopGlide();
    };
    const up = () => {
      this.#touches = Math.max(0, this.#touches - 1);
      if (!this.#touches) this.#scrolled();
    };
    target.addEventListener("touchstart", down, { passive: true });
    target.addEventListener("touchend", up, { passive: true });
    target.addEventListener("touchcancel", up, { passive: true });
  }

  /** A mouse wheel turns downward; a leftward strip follows it. */
  #watchWheel(target: Document | HTMLElement) {
    target.addEventListener(
      "wheel",
      (e) => {
        const { deltaX, deltaY } = e as WheelEvent;
        if (!this.#vertical || Math.abs(deltaY) <= Math.abs(deltaX)) return;
        e.preventDefault();
        // Lines (a mouse in Firefox) or pixels.
        this.#glide((e as WheelEvent).deltaMode === 1 ? deltaY * 40 : deltaY);
      },
      { passive: false },
    );
  }

  /** Move the strip by `delta` where the browser has no scroll of its
   *  own to do it with — a wheel turning downward over a leftward strip,
   *  a key asking for a screen — as a critically damped spring towards
   *  where it has been asked to be. Its speed carries over from one
   *  request to the next and dies away at the end: no restart at each
   *  notch, no sudden stop. A reader who asked for reduced motion is
   *  moved at once. */
  #glide(delta: number) {
    const max = Math.max(0, this.#extent - this.#screen);
    const target = Math.max(
      0,
      Math.min(max, (this.#glideTarget ?? this.#at) + delta),
    );
    if (this.#o.reducedMotion()) {
      this.#stopGlide();
      this.#at = target;
      return;
    }
    if (this.#glideTarget == null) {
      this.#glideAt = this.#at;
      this.#glideSpeed = 0;
      this.#glideTime = performance.now();
    }
    this.#glideTarget = target;
    if (this.#glideFrame) return;
    const step = (now: number) => {
      this.#glideFrame = 0;
      const to = this.#glideTarget;
      if (to == null || this.#destroyed) return;
      const t = Math.min(0.05, Math.max(0, (now - this.#glideTime) / 1000));
      this.#glideTime = now;
      const off = this.#glideAt - to;
      const pull = this.#glideSpeed + GLIDE_STIFFNESS * off;
      const decay = Math.exp(-GLIDE_STIFFNESS * t);
      this.#glideAt = to + (off + pull * t) * decay;
      this.#glideSpeed =
        (this.#glideSpeed - GLIDE_STIFFNESS * pull * t) * decay;
      if (
        Math.abs(this.#glideAt - to) < 0.5 &&
        Math.abs(this.#glideSpeed) < 8
      ) {
        this.#at = to;
        this.#glideTarget = null;
        return;
      }
      this.#at = this.#glideAt;
      this.#glideFrame = requestAnimationFrame(step);
    };
    this.#glideFrame = requestAnimationFrame(step);
  }

  #stopGlide() {
    cancelAnimationFrame(this.#glideFrame);
    this.#glideFrame = 0;
    this.#glideTarget = null;
  }

  #rested() {
    if (this.#destroyed || this.#touches) return;
    const first = this.#chapters[0];
    if (!first) return;
    // (A glide still on its way has the position: the canvas is shifted
    // when it too has come to rest.)
    if (this.#glideTarget == null) {
      const start = this.#adjacent(first.index, -1) == null;
      if (start && first.top !== 0) this.#rebase(-first.top);
      else if (!start && first.top < ORIGIN_LOW) this.#rebase(ORIGIN);
    }
    this.#pin();
    this.#tell("scroll");
    this.#readOut();
  }

  /** Shift the whole canvas, and the scroll position with it, in one
   *  frame: nothing moves on screen, and where the reader is in their
   *  chapter is what it was — nothing to report. */
  #rebase(delta: number) {
    const top = this.#at;
    for (const chapter of this.#chapters) chapter.top += delta;
    this.#layout();
    this.#at = top + delta;
    this.#note(`rebased ${delta}`);
  }

  /** Report where the reader is — unless it is where the last report
   *  said (`force`: a destination reached is reported even then). */
  #tell(reason: string, force = false) {
    const pinned = this.#pinned;
    if (!pinned || this.#destroyed) return;
    const offset = this.#at - pinned.top;
    const told = this.#told;
    if (
      !force &&
      told &&
      told.index === pinned.index &&
      Math.abs(told.offset - offset) < 1
    )
      return;
    this.#told = { index: pinned.index, offset };
    this.#o.onrelocate({
      reason,
      index: pinned.index,
      fraction: Math.max(0, Math.min(1, offset / Math.max(1, pinned.height))),
      range: this.#visible(pinned, offset),
    });
  }

  /** The text of `chapter` on screen when the screen's leading edge is
   *  `offset` into it. Past the chapter's end (the bare paper after it)
   *  that is its last lines. */
  #visible(chapter: Chapter, offset: number): Range | null {
    const { doc, height } = chapter;
    if (!doc.body) return null;
    // Rects as if the strip ran left to right: `left` is a box's start
    // along it, `right` its end.
    const along = chapter.vertical
      ? ({ left, right }: DOMRect) => ({
          left: height - right,
          right: height - left,
        })
      : ({ top, bottom }: DOMRect) => ({ left: top, right: bottom });
    const start = Math.max(
      0,
      Math.min(offset + LINE_INSET, height - LINE_INSET),
    );
    const end = Math.max(start, offset + this.#screen);
    try {
      let range = getVisibleRange(doc, start, end, along) as Range;
      // Nothing whole in the window (a picture larger than the screen):
      // the first thing after the line, however far.
      if (
        range.collapsed &&
        range.startContainer === doc.body &&
        range.startOffset === 0 &&
        start > LINE_INSET
      )
        range = getVisibleRange(doc, start, height, along) as Range;
      toLineStart(range, start, along);
      return range;
    } catch (e) {
      console.warn(e);
      return null;
    }
  }

  #note(what: string, index?: number, ms?: number) {
    this.log.push({ at: Math.round(performance.now()), what, index, ms });
    if (this.log.length > 200) this.log.shift();
  }

  /** The debug line in the corner (goes with the settings entry). */
  #readOut() {
    const chapters = this.#chapters;
    const pinned = this.#pinned;
    if (!pinned || !chapters.length) return;
    const into = this.#at - pinned.top;
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

type Along = (rect: DOMRect) => { left: number; right: number };

/**
 * Move the start of `range` to the first character of its text node
 * that is not wholly before `start` along the strip — the beginning of
 * the line the reading line cuts, or of the first one after it.
 *
 * The paginator's walk finds the node; where in it the visible text
 * begins it finds by bisection between "before" and "after", which a
 * page's edge always separates. A scrolled screen's edge as a rule cuts
 * through a line, and the walk then stops anywhere in that line: the
 * same place read twice would be saved as two positions.
 */
function toLineStart(range: Range, start: number, along: Along) {
  const node = range.startContainer;
  if (node.nodeType !== 3) return;
  const length = (node as Text).length;
  const probe = node.ownerDocument!.createRange();
  // Whether character `i` reaches past the line. (One with no box of
  // its own — collapsed white space — is judged by the next that has.)
  const past = (i: number): boolean => {
    for (let j = i; j < length && j < i + 16; j++) {
      probe.setStart(node, j);
      probe.setEnd(node, j + 1);
      for (const rect of Array.from(probe.getClientRects()))
        if (rect.width > 0 || rect.height > 0) return along(rect).right > start;
    }
    return true;
  };
  let lo = 0;
  let hi = range.endContainer === node ? range.endOffset : length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (past(mid)) hi = mid;
    else lo = mid + 1;
  }
  // Never between the halves of one character.
  const code = (node as Text).data.charCodeAt(lo);
  if (lo > 0 && code >= 0xdc00 && code <= 0xdfff) lo -= 1;
  range.setStart(node, lo);
}

/** Half the space a line of text has beyond its glyphs' own box. */
function leadOf(anchor: unknown, rect: DOMRect, vertical: boolean): number {
  const start = (anchor as Partial<Range> | null)?.startContainer;
  if (!start) return 0;
  const el = start.nodeType === 1 ? (start as Element) : start.parentElement;
  const view = el?.ownerDocument.defaultView;
  if (!el || !view) return 0;
  const line = parseFloat(view.getComputedStyle(el).lineHeight);
  if (!Number.isFinite(line)) return 0;
  const glyph = vertical ? rect.width : rect.height;
  return Math.max(0, Math.min(40, (line - glyph) / 2));
}

/** The first box of an anchor: an element's, or a range's — a collapsed
 *  range has none in some engines and is given a character to stand on. */
function firstRect(anchor: unknown): DOMRect | null {
  if (!anchor || typeof anchor !== "object") return null;
  let target = anchor as Range | Element;
  if ("collapsed" in target && target.collapsed) {
    const range = target.cloneRange();
    const node = range.endContainer;
    const offset = range.endOffset;
    if (node.nodeType === 1) {
      target =
        (node.childNodes[offset] as Element | undefined) ?? (node as Element);
      if (target.nodeType !== 1) {
        range.selectNode(target);
        target = range;
      }
    } else {
      const length = (node as Text).length;
      if (offset < length) range.setEnd(node, offset + 1);
      else if (offset > 0) range.setStart(node, offset - 1);
      else if (node.parentElement) target = node.parentElement;
      if (target === anchor) target = range;
    }
  }
  const rects = target.getClientRects?.();
  if (!rects?.length) return null;
  return Array.from(rects).find((r) => r.width > 0 && r.height > 0) ?? rects[0];
}
