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
 * key), a wheel followed along a leftward strip, the line put back
 * after a restyle or a new screen size, and the whole canvas shifted
 * (#rebase, at rest or with a restyle) — the book's first chapter has
 * to sit at the canvas's start for the browser to stop there.
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
 * Each chapter carries an overlayer (the core's, for the highlight
 * layer) over its frame, redrawn when the chapter changes size.
 *
 * A chapter that does not load leaves the strip ending where it did:
 * bare paper, a spinner while an attempt is out. It is asked for again
 * after a while by itself (while there is a connection), when the core
 * says a text has arrived, when the connection is back, and when the
 * reader asks (retry). The reader is told once — `onfail` — when they
 * stand at that seam, not at every attempt and not for a chapter still
 * far ahead of them; `onrecover` says it has joined after all.
 *
 * New styles, a new layout or a new screen size are taken in place
 * (restyle, and the scroller's own resize): every mounted chapter is
 * styled and measured again where it stands, and the strip is moved so
 * that the line that was at the reading line is there again.
 *
 * `log` keeps the last two hundred things the strip did (a chapter
 * built, joined, let go, failed; the canvas shifted; a restyle) in
 * memory, for probes and tests: nothing is drawn from it.
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
  /** A chapter is measured and about to stand on the strip: `attach`
   *  takes the overlayer that is to lie over it. */
  onoverlayer: (detail: {
    doc: Document;
    index: number;
    attach: (overlayer: StripOverlayer) => void;
  }) => void;
  /** A chapter's document is gone (let go, or the strip built anew). */
  ongone: (detail: { doc: Document; index: number }) => void;
  /** The reader stands at an end of the strip whose next chapter
   *  (`index`) could not be loaded. Once for a seam that stays stuck. */
  onfail: (detail: { index: number; dir: 1 | -1 }) => void;
  /** A chapter that had failed at that end has joined. */
  onrecover: (detail: { dir: 1 | -1 }) => void;
  /** Whether there is a connection to ask a missing chapter over. */
  online: () => boolean;
  /** The mounted chapters were laid out again where they stand (new
   *  styles, a new screen size): what is drawn over them has moved. */
  onreflow: () => void;
}

/** What the strip asks of an overlayer: an element to lay over the
 *  chapter (sized to it, in its document's coordinates) and a redraw. */
export interface StripOverlayer {
  element: Element;
  redraw(): void;
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
/** How long after a restyle a late change of size is still its doing. */
const KEEP_MS = 1500;
/** The reading line stands this far inside the screen's leading edge: a
 *  line of which only a sliver is left there (the scroller keeps whole
 *  pixels, text does not) is not the line being read. */
const LINE_INSET = 2;

/** The line at the reading line, as a re-anchoring holds it. */
interface Line {
  chapter: Chapter;
  point: Range | null;
  delta: number;
  thick: number;
  fraction: number;
}

interface Chapter {
  index: number;
  frame: HTMLDivElement;
  doc: Document;
  /** Set the strip's way at build — the axis it was measured along. */
  vertical: boolean;
  top: number;
  height: number;
  overlayer: StripOverlayer | null;
  /** The injected styles: ours before the book's, ours after, and the
   *  strip's layout last. */
  styles: [HTMLStyleElement, HTMLStyleElement, HTMLStyleElement];
  /** Size the frame to the text; whether that changed it. */
  measure: () => boolean;
  observer: ResizeObserver;
  unload: () => void;
}

export class ScrollStrip {
  #o: StripOptions;
  #scroller: HTMLDivElement;
  #canvas: HTMLDivElement;
  /** The mounted chapters, in reading order, with no gap between them. */
  #chapters: Chapter[] = [];
  #pinned: Chapter | null = null;
  #vertical = false;
  /** A selection is being drawn out by a finger: the strip holds still. */
  #held = false;
  /** The attempt out at each end: resolves to whether a chapter joined. */
  #attempt: Record<1 | -1, Promise<boolean> | null> = { 1: null, [-1]: null };
  #retryAt: Record<1 | -1, number> = { 1: 0, [-1]: 0 };
  #retryTimers: Record<1 | -1, ReturnType<typeof setTimeout> | null> = {
    1: null,
    [-1]: null,
  };
  /** The chapter that would not load at each end, and whether the
   *  reader has been told. */
  #stuck: Record<1 | -1, number | null> = { 1: null, [-1]: null };
  #said: Record<1 | -1, boolean> = { 1: false, [-1]: false };
  /** The line last reported at the reading line: what a new screen size
   *  is re-anchored to (by then the text has already moved). */
  #line: Line | null = null;
  /** The line a restyle put back, for a moment after it: a font that
   *  arrives late moves the text once more. */
  #kept: { line: Line; at: number; until: number } | null = null;
  #sizeObserver: ResizeObserver | null = null;
  #size = "";
  #onOnline = () => this.poke();
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
    options.container.append(scroller);
    this.#scroller = scroller;
    this.#canvas = canvas;
    scroller.addEventListener("scroll", () => this.#scrolled(), {
      passive: true,
    });
    this.#watchTouches(scroller);
    this.#watchWheel(scroller);
    this.#setAxis(false);
    globalThis.addEventListener?.("online", this.#onOnline);
    if (typeof ResizeObserver === "function") {
      this.#sizeObserver = new ResizeObserver(() => this.#resized());
      this.#sizeObserver.observe(scroller);
    }
  }

  #setAxis(vertical: boolean) {
    this.#vertical = vertical;
    const scroll = this.#held ? "hidden" : "auto";
    Object.assign(
      this.#scroller.style,
      vertical
        ? { overflowX: scroll, overflowY: "hidden", direction: "rtl" }
        : { overflowX: "hidden", overflowY: scroll, direction: "ltr" },
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
  getContents(): {
    index: number;
    doc: Document;
    overlayer: StripOverlayer | null;
  }[] {
    const pinned = this.#pinned;
    const rest = this.#chapters.filter((chapter) => chapter !== pinned);
    return (pinned ? [pinned, ...rest] : rest).map(
      ({ index, doc, overlayer }) => ({ index, doc, overlayer }),
    );
  }

  /** The book's last chapter is mounted and its end is on screen. */
  get atEnd(): boolean {
    const last = this.#chapters[this.#chapters.length - 1];
    if (!last || this.#adjacent(last.index, 1) != null) return false;
    return this.#at + this.#screen >= last.top + last.height - 1;
  }

  /** Keep the strip from following the finger (true) while a long
   *  press's selection is drawn out, and give it back (false). Where it
   *  stands is not changed by either. */
  hold(on: boolean) {
    if (on === this.#held) return;
    this.#held = on;
    this.#setAxis(this.#vertical);
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
    this.#moveTo(chapter.top + this.#offsetOf(chapter, target.anchor));
    this.#pin();
    this.#fill();
    this.#tell(reason, true);
  }

  /** Stand at `value` along the strip, or as near as the canvas lets
   *  the screen go. (Kept within the canvas here, not left to the
   *  scroller: what it reports of itself right after a write is not
   *  always what it settles on, and the place told must be the place.) */
  #moveTo(value: number) {
    const max = Math.max(0, this.#extent - this.#screen);
    this.#at = Math.max(0, Math.min(max, value));
  }

  /** Build the strip anew around `target`. What is on screen stays
   *  until the chapter is ready to take its place. */
  async open(
    target: Pick<NavTarget, "index" | "anchor">,
    reason = "navigation",
  ): Promise<void> {
    const generation = ++this.#generation;
    for (const dir of [1, -1] as const) {
      this.#attempt[dir] = null;
      this.#pending(dir, false);
      this.#unstick(dir);
    }
    this.#kept = null;
    this.#line = null;
    const chapter = await this.#build(target.index, generation, true);
    if (!chapter) return;
    this.#stopGlide();
    for (const old of this.#chapters) this.#discard(old);
    this.#setAxis(chapter.vertical);
    chapter.frame.style[chapter.vertical ? "height" : "width"] = "100%";
    chapter.top = this.#adjacent(target.index, -1) == null ? 0 : ORIGIN;
    this.#chapters = [chapter];
    this.#pinned = chapter;
    this.#layout();
    chapter.frame.style.visibility = "";
    this.#moveTo(chapter.top + this.#offsetOf(chapter, target.anchor));
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
    for (const dir of [1, -1] as const) {
      this.#pending(dir, false);
      const timer = this.#retryTimers[dir];
      if (timer) clearTimeout(timer);
    }
    globalThis.removeEventListener?.("online", this.#onOnline);
    this.#sizeObserver?.disconnect();
    this.#stopGlide();
    for (const chapter of this.#chapters) this.#discard(chapter);
    this.#chapters = [];
    this.#pinned = null;
    this.#scroller.remove();
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
    // As the paginator's frames (on iOS the gesture layer's CSP keeps a
    // book's scripts from running, there as here).
    iframe.setAttribute("sandbox", "allow-same-origin allow-scripts");
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
    const styles = this.#o.styles();
    const [before, after] = Array.isArray(styles) ? styles : ["", styles];
    const first = doc.createElement("style");
    first.textContent = before;
    doc.head.prepend(first);
    const last = doc.createElement("style");
    last.textContent = after;
    doc.head.append(last);
    const layout = doc.createElement("style");
    doc.head.append(layout);
    const mode = doc.defaultView?.getComputedStyle(doc.body).writingMode;
    const ownVertical = !!mode && mode.startsWith("vertical");
    const vertical = decide ? ownVertical : this.#vertical;
    // Across the strip a chapter has the screen. The chapter the strip
    // is opened on is measured before the strip runs its way (what is on
    // screen stays as it is meanwhile): it is given the screen's size in
    // so many pixels, and the canvas's once it stands on it (see open).
    const across = decide
      ? `${vertical ? this.#scroller.clientHeight : this.#scroller.clientWidth}px`
      : "100%";
    Object.assign(
      frame.style,
      vertical
        ? { top: "0", right: "0", height: across }
        : { top: "0", left: "0", width: across },
    );
    Object.assign(
      iframe.style,
      vertical
        ? { height: "100%", width: "0" }
        : { width: "100%", height: "0" },
    );
    layout.textContent = this.#layoutCss(vertical);
    this.#o.onload({ doc, index, ownVertical });
    this.#watchTouches(doc);
    this.#watchWheel(doc);
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
      overlayer: null,
      styles: [first, last, layout],
      measure: () => false,
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
    chapter.measure = measure;
    measure();
    // The document's own window makes the observer: its callback then
    // runs in the frame the text was laid out in, before it is painted.
    const Observer = doc.defaultView?.ResizeObserver ?? ResizeObserver;
    chapter.observer = new Observer(() => {
      if (!measure()) return;
      // The marks are measured from the text: where it went, they go.
      chapter.overlayer?.redraw();
      if (!this.#chapters.includes(chapter)) return;
      this.#note("resized", index);
      this.#layout();
      // Just after a restyle: a font come late has moved the line that
      // was put back, and the reader has not moved since — once more.
      const kept = this.#kept;
      if (
        kept &&
        performance.now() < kept.until &&
        Math.abs(this.#at - kept.at) < 2 &&
        this.#chapters.includes(kept.line.chapter)
      ) {
        this.#reanchor(kept.line);
        this.#o.onreflow();
        return;
      }
      // Should that have moved the reader (a strip that became shorter
      // than where they stood), it was not they who moved.
      this.#tell("anchor");
    });
    chapter.observer.observe(doc.documentElement);
    this.#o.onoverlayer({
      doc,
      index,
      attach: (overlayer) => {
        chapter.overlayer = overlayer;
        frame.append(overlayer.element);
      },
    });
    this.#note("built", index, performance.now() - started);
    return chapter;
  }

  #discard(chapter: Chapter) {
    chapter.observer.disconnect();
    this.#o.ongone({ doc: chapter.doc, index: chapter.index });
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
    if (last.top + last.height - bottom < AHEAD * screen) void this.#extend(1);
    if (top - first.top < AHEAD * screen) void this.#extend(-1);
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

  /** Bring the next chapter onto that end. Resolves to whether one
   *  joined. An attempt already out is the attempt; one that failed is
   *  not made again before its time unless `now` says so. */
  #extend(dir: 1 | -1, now = false): Promise<boolean> {
    const out = this.#attempt[dir];
    if (out) return out;
    const chapters = this.#chapters;
    const edge = dir > 0 ? chapters[chapters.length - 1] : chapters[0];
    const index = edge ? this.#adjacent(edge.index, dir) : null;
    if (index == null) return Promise.resolve(false);
    if (!now) {
      if (performance.now() < this.#retryAt[dir]) return Promise.resolve(false);
      // Without a connection a chapter that failed is not asked for
      // again unasked: nothing has changed that would bring it.
      if (this.#stuck[dir] != null && !this.#o.online())
        return Promise.resolve(false);
    }
    const generation = this.#generation;
    this.#pending(dir, true);
    const attempt: Promise<boolean> = this.#build(index, generation)
      .then((chapter) => {
        if (generation !== this.#generation) {
          if (chapter) this.#discard(chapter);
          return false;
        }
        this.#attempt[dir] = null;
        this.#pending(dir, false);
        if (!chapter) return false;
        // Still the neighbour of the end it was built for, and set the
        // way the strip (opened anew meanwhile, perhaps) now runs?
        const mounted = this.#chapters;
        const end = dir > 0 ? mounted[mounted.length - 1] : mounted[0];
        if (
          !end ||
          this.#adjacent(end.index, dir) !== index ||
          chapter.vertical !== this.#vertical
        ) {
          this.#discard(chapter);
          return false;
        }
        if (dir > 0) mounted.push(chapter);
        else mounted.unshift(chapter);
        this.#layout();
        chapter.frame.style.visibility = "";
        // (It may be the one under the reading line: a strip opened at
        // the book's end stands before its only chapter until the one
        // before has joined. Where each stands is unchanged.)
        const before = this.#pinned;
        this.#pin();
        this.#note("joined", index);
        this.#unstick(dir);
        // The reader was waiting for it at the seam: they are in it now.
        if (this.#pinned !== before) this.#tell("scroll");
        this.#fill();
        return true;
      })
      .catch((e: unknown) => {
        if (generation !== this.#generation) return false;
        console.warn(e);
        this.#attempt[dir] = null;
        this.#pending(dir, false);
        this.#note("failed", index);
        this.#stick(dir, index);
        return false;
      });
    this.#attempt[dir] = attempt;
    return attempt;
  }

  /** The chapter at that end would not load: it is asked for again in
   *  a while, and the reader is told if they are standing there. */
  #stick(dir: 1 | -1, index: number) {
    if (this.#stuck[dir] !== index) this.#said[dir] = false;
    this.#stuck[dir] = index;
    this.#retryAt[dir] = performance.now() + RETRY_MS;
    const timer = this.#retryTimers[dir];
    if (timer) clearTimeout(timer);
    this.#retryTimers[dir] = setTimeout(() => {
      this.#retryTimers[dir] = null;
      if (!this.#destroyed) this.#fill();
    }, RETRY_MS + 50);
    this.#say(dir);
  }

  #unstick(dir: 1 | -1) {
    const timer = this.#retryTimers[dir];
    if (timer) clearTimeout(timer);
    this.#retryTimers[dir] = null;
    this.#retryAt[dir] = 0;
    const was = this.#stuck[dir] != null;
    this.#stuck[dir] = null;
    this.#said[dir] = false;
    if (was) this.#o.onrecover({ dir });
  }

  /** Tell the reader of a chapter that would not load — once, and only
   *  when the bare paper where it should be is on their screen. */
  #say(dir: 1 | -1) {
    const index = this.#stuck[dir];
    const chapters = this.#chapters;
    if (index == null || this.#said[dir] || !chapters.length) return;
    // (Still moving: said when the strip has come to rest.)
    if (this.#restTimer || this.#touches) return;
    const at = this.#at;
    const last = chapters[chapters.length - 1];
    const reached =
      dir > 0
        ? last.top + last.height < at + this.#screen - 1
        : chapters[0].top > at + 1;
    if (!reached) return;
    this.#said[dir] = true;
    this.#o.onfail({ index, dir });
  }

  /** The reader asks for the chapter at that end again, now. Resolves
   *  to whether it joined. */
  retry(dir: 1 | -1): Promise<boolean> {
    return this.#extend(dir, true);
  }

  /** Something may have changed for a chapter that would not load (a
   *  text has arrived, the connection is back): ask again at once. */
  poke() {
    if (this.#destroyed) return;
    for (const dir of [1, -1] as const)
      if (this.#stuck[dir] != null) void this.#extend(dir, true);
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
    this.#restTimer = null;
    if (this.#destroyed || this.#touches) return;
    const first = this.#chapters[0];
    if (!first) return;
    // (A glide still on its way has the position: the canvas is shifted
    // when it too has come to rest.)
    if (this.#glideTarget == null) this.#settleOrigin();
    this.#pin();
    this.#tell("scroll");
    // At an end whose chapter would not come: said now (after the move
    // that brought the reader here has been told, not before).
    this.#say(1);
    this.#say(-1);
  }

  /** Put the canvas's start where it belongs: at the book's first
   *  chapter when that is mounted, far enough before the first mounted
   *  one otherwise. */
  #settleOrigin() {
    const first = this.#chapters[0];
    if (!first) return;
    const start = this.#adjacent(first.index, -1) == null;
    if (start && first.top !== 0) this.#rebase(-first.top);
    else if (!start && first.top < ORIGIN_LOW) this.#rebase(ORIGIN);
  }

  /** Shift the whole canvas, and the scroll position with it, in one
   *  frame: nothing moves on screen, and where the reader is in their
   *  chapter is what it was — nothing to report. */
  #rebase(delta: number) {
    const top = this.#at;
    for (const chapter of this.#chapters) chapter.top += delta;
    this.#layout();
    this.#at = top + delta;
    if (this.#kept) this.#kept.at += delta;
    this.#note(`rebased ${delta}`);
  }

  /** Report where the reader is — unless it is where the last report
   *  said (`force`: a destination reached is reported even then). */
  #tell(reason: string, force = false) {
    if (!this.#pinned || this.#destroyed) return;
    // The place is the chapter under the reading line — except at the
    // very end of the book, where it is the last chapter though that be
    // too short to reach the line: a finished book is in its last
    // chapter, by name and by the position saved. (What is pinned, and
    // so the layout, is the chapter under the line all the same.)
    const last = this.#chapters[this.#chapters.length - 1];
    const chapter = this.atEnd && last ? last : this.#pinned;
    const offset = this.#at - chapter.top;
    const told = this.#told;
    if (
      !force &&
      told &&
      told.index === chapter.index &&
      Math.abs(told.offset - offset) < 1
    )
      return;
    this.#told = { index: chapter.index, offset };
    const range = offset < 0 ? null : this.#visible(chapter, offset);
    this.#line = this.#lineOf(chapter, offset, range);
    this.#o.onrelocate({
      reason,
      index: chapter.index,
      fraction: Math.max(0, Math.min(1, offset / Math.max(1, chapter.height))),
      // (A last chapter the line has not reached is reported by its
      // beginning — which is on screen — and no narrower.)
      range,
    });
  }

  /** What a re-anchoring needs of the line at the reading line: where
   *  its text begins (a point that lives through a new layout), how far
   *  that is from the line, and how thick the line is. Without text
   *  there (a picture, the bare paper) the share of the chapter passed. */
  #lineOf(chapter: Chapter, offset: number, range: Range | null): Line {
    const fraction = offset / Math.max(1, chapter.height);
    const line: Line = { chapter, point: null, delta: 0, thick: 0, fraction };
    if (!range) return line;
    const point = range.cloneRange();
    point.collapse(true);
    const rect = firstRect(point.cloneRange());
    if (!rect) return line;
    const box = this.#along(chapter, rect);
    return {
      chapter,
      point,
      delta: box.left - offset,
      thick: box.right - box.left,
      fraction,
    };
  }

  /** A rect of a chapter's document as if the strip ran left to right:
   *  `left` is a box's start along it, `right` its end. */
  #along(chapter: Chapter, rect: DOMRect): { left: number; right: number } {
    return chapter.vertical
      ? { left: chapter.height - rect.right, right: chapter.height - rect.left }
      : { left: rect.top, right: rect.bottom };
  }

  /**
   * Take new styles and a new layout in place: every mounted chapter is
   * styled and measured again where it stands — its frame, its document
   * and what is drawn over it stay — and the strip is moved so that the
   * line at the reading line is there again. Styles that change no
   * measure (a theme) move nothing.
   */
  restyle() {
    const pinned = this.#pinned;
    if (!pinned || this.#destroyed) return;
    // A reader who has not moved since the last restyle is put back on
    // the line that one began with: changing a setting and changing it
    // back ends where it started, not a line earlier each time.
    const kept = this.#kept;
    if (
      kept &&
      Math.abs(this.#at - kept.at) < 2 &&
      this.#chapters.includes(kept.line.chapter)
    ) {
      this.#pinned = kept.line.chapter;
      this.#relay(kept.line);
      return;
    }
    const offset = this.#at - pinned.top;
    const line = this.#lineOf(
      pinned,
      offset,
      offset < 0 ? null : this.#visible(pinned, offset),
    );
    this.#relay(line);
  }

  /** The screen changed size (a window resized, a phone turned): the
   *  text has been laid out for it already, so the line to put back is
   *  the one last reported. */
  #resized() {
    const size = `${this.#scroller.clientWidth}x${this.#scroller.clientHeight}`;
    const was = this.#size;
    this.#size = size;
    if (!was || was === size || !this.#pinned || this.#destroyed) return;
    const kept = this.#kept;
    const held =
      kept && Math.abs(this.#at - kept.at) < 2 ? kept.line : this.#line;
    const line = held && this.#chapters.includes(held.chapter) ? held : null;
    if (line) this.#pinned = line.chapter;
    this.#relay(
      line ?? this.#lineOf(this.#pinned, this.#at - this.#pinned.top, null),
    );
  }

  /** Style and measure every chapter again, lay them out from the one
   *  the line is in, and put the line back. */
  #relay(line: Line) {
    const styles = this.#o.styles();
    const [before, after] = Array.isArray(styles) ? styles : ["", styles];
    for (const chapter of this.#chapters) {
      const [first, last, layout] = chapter.styles;
      if (first.textContent !== before) first.textContent = before;
      if (last.textContent !== after) last.textContent = after;
      const css = this.#layoutCss(chapter.vertical);
      if (layout.textContent !== css) layout.textContent = css;
    }
    for (const chapter of this.#chapters) {
      chapter.measure();
      chapter.overlayer?.redraw();
    }
    this.#layout();
    // (A chapter before the line that grew has pushed the ones before it
    // back, perhaps past the canvas's start: the canvas goes with them.)
    this.#settleOrigin();
    this.#reanchor(line);
    this.#kept = {
      line,
      at: this.#at,
      until: performance.now() + KEEP_MS,
    };
    this.#note("restyled");
    this.#o.onreflow();
  }

  /** Stand where `line` is at the reading line again. A layout that
   *  left it where it was is not answered with a write. */
  #reanchor(line: Line) {
    const { chapter } = line;
    let offset = line.fraction * chapter.height;
    const rect = line.point ? firstRect(line.point.cloneRange()) : null;
    if (rect) {
      const box = this.#along(chapter, rect);
      const thick = box.right - box.left;
      // As far inside the line as before, by the line's new measure. (A
      // line that began after the reading line — the head of a chapter,
      // under its margin — keeps that distance as it was.)
      const scale = line.delta < 0 && line.thick > 0 ? thick / line.thick : 1;
      offset = box.left - line.delta * scale;
    }
    const target = chapter.top + Math.floor(offset);
    if (Math.abs(target - this.#at) >= 1) this.#moveTo(target);
    if (this.#kept) this.#kept.at = this.#at;
    this.#pin();
    this.#fill();
    this.#tell("anchor");
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
