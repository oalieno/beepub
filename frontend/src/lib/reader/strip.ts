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
 * A horizontal book's strip runs downward, a vertical book's leftward
 * (an rtl scroller: the position along it is -scrollLeft). The chapter
 * the strip is opened on decides, and every chapter is set that way. A
 * chapter's `top` and `height` below are its start and its extent ALONG
 * the strip, whichever way that runs.
 *
 * Not here yet: saved progress, highlights, selection menu, links, keys.
 */
import type { Book, NavTarget } from "./core";

export interface StripOptions {
  container: HTMLElement;
  book: Book;
  styles: () => string | [string, string];
  /** Per-section DOM preparation shared with the paginator's sections. */
  prepare: (doc: Document) => void;
  /** The reader's left/right and top/bottom margins, px. */
  marginX: number;
  marginY: number;
  /** Longest line, px: of horizontal text, and of vertical text. */
  measure: number;
  verticalMeasure: number;
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
/** A chapter on its way is not announced before this: a spinner that
 *  comes and goes at once is worse than the bare paper. */
const SPINNER_AFTER_MS = 400;
/** How quickly the wheel's spring closes on its target, 1/s. */
const WHEEL_STIFFNESS = 8;

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
  #vertical = false;
  /** Whether the opened chapter has said which way the strip runs. */
  #decided = false;
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
  #wheelTarget: number | null = null;
  #wheelFrame = 0;
  /** The spring's own position (the scroller rounds what it is given),
   *  its speed in px/s and the time of its last step. */
  #wheelAt = 0;
  #wheelSpeed = 0;
  #wheelTime = 0;
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
    this.#pending(1, false);
    this.#pending(-1, false);
    this.#wheelTarget = null;
    this.#decided = false;
    const chapter = await this.#build(target.index, generation);
    if (!chapter) return;
    chapter.top = this.#adjacent(target.index, -1) == null ? 0 : ORIGIN;
    this.#chapters = [chapter];
    this.#pinned = chapter;
    this.#layout();
    chapter.frame.style.visibility = "";
    this.#at = chapter.top + this.#offsetOf(chapter, target.anchor);
    this.#fill();
    this.#report();
  }

  destroy() {
    this.#destroyed = true;
    this.#generation++;
    if (this.#restTimer) clearTimeout(this.#restTimer);
    this.#pending(1, false);
    this.#pending(-1, false);
    cancelAnimationFrame(this.#wheelFrame);
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
    // The iframe is as large as its document and never scrolls: a rect
    // in it is measured from the chapter's own edges.
    return Math.max(0, this.#vertical ? chapter.height - rect.right : rect.top);
  }

  #adjacent(index: number, dir: 1 | -1): number | null {
    const { sections } = this.#o.book;
    for (let i = index + dir; i >= 0 && i < sections.length; i += dir)
      if (sections[i].linear !== "no") return i;
    return null;
  }

  #layoutCss(): string {
    const { marginX, marginY, measure, verticalMeasure } = this.#o;
    const vertical = this.#vertical;
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
    if (!this.#decided) {
      // The chapter the strip is opened on says which way it runs.
      this.#decided = true;
      const mode = doc.defaultView?.getComputedStyle(doc.body).writingMode;
      this.#setAxis(!!mode && mode.startsWith("vertical"));
    }
    const vertical = this.#vertical;
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
    last.textContent += this.#layoutCss();
    this.#o.prepare(doc);
    this.#watchTouches(doc);
    this.#watchWheel(doc);
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
      this.#pin();
      this.#fill();
      this.#report();
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
        this.#pending(dir, false);
        this.#retryAt[dir] = performance.now() + RETRY_MS;
        this.#note("failed", index);
        this.#report();
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
    const down = () => (this.#touches += 1);
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
        this.#wheel((e as WheelEvent).deltaMode === 1 ? deltaY * 40 : deltaY);
      },
      { passive: false },
    );
  }

  /** A wheel turns downward and a leftward strip has no axis of the
   *  browser's to follow it with, so the strip follows it itself: as a
   *  critically damped spring towards where the wheel has asked for. Its
   *  speed carries over from one notch to the next and dies away at the
   *  end — no restart at each notch, no sudden stop. */
  #wheel(delta: number) {
    const max = Math.max(0, this.#extent - this.#screen);
    if (this.#wheelTarget == null) {
      this.#wheelAt = this.#at;
      this.#wheelSpeed = 0;
      this.#wheelTime = performance.now();
    }
    this.#wheelTarget = Math.max(
      0,
      Math.min(max, (this.#wheelTarget ?? this.#at) + delta),
    );
    if (this.#wheelFrame) return;
    const step = (now: number) => {
      this.#wheelFrame = 0;
      const target = this.#wheelTarget;
      if (target == null || this.#destroyed) return;
      const t = Math.min(0.05, Math.max(0, (now - this.#wheelTime) / 1000));
      this.#wheelTime = now;
      const off = this.#wheelAt - target;
      const pull = this.#wheelSpeed + WHEEL_STIFFNESS * off;
      const decay = Math.exp(-WHEEL_STIFFNESS * t);
      this.#wheelAt = target + (off + pull * t) * decay;
      this.#wheelSpeed =
        (this.#wheelSpeed - WHEEL_STIFFNESS * pull * t) * decay;
      if (
        Math.abs(this.#wheelAt - target) < 0.5 &&
        Math.abs(this.#wheelSpeed) < 8
      ) {
        this.#at = target;
        this.#wheelTarget = null;
        return;
      }
      this.#at = this.#wheelAt;
      this.#wheelFrame = requestAnimationFrame(step);
    };
    this.#wheelFrame = requestAnimationFrame(step);
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
    const top = this.#at;
    for (const chapter of this.#chapters) chapter.top += delta;
    this.#layout();
    this.#at = top + delta;
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
