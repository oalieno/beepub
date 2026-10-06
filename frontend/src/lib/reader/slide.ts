/**
 * CoverSlide — the "slide" page turn: one page is a sheet that moves over
 * another page that stays still, the way a stack of sheets is leafed
 * through. The lower page number is always the upper sheet:
 *
 *   next      the page on screen follows the finger and slides away; the
 *             next page is already lying still underneath;
 *   previous  the previous page slides in from the side and covers the
 *             page on screen, which stays still.
 *
 * Two renderings of the book have to be visible at once, so the reader
 * keeps a second paginator — the ghost — showing the neighbouring page
 * (the same section one page on, or the adjacent section at a chapter
 * boundary). The ghost is a full paginator fed the same styles, layout
 * parameters and per-section adjustments as the live one, so the page it
 * shows is laid out by the same code from the same inputs; it is inert
 * (no pointer events, no focus, no listeners of the reader's) and never
 * reported by the core as a section on screen.
 *
 * Only a layer's horizontal transform animates. How the paginator stacks
 * a section's pages internally (side by side, or top to bottom for
 * vertical text) does not matter, which is what lets vertical books
 * slide.
 *
 * The ghost never becomes the live page. A completed turn ends with the
 * ghost lying over the live paginator, which then makes the same turn
 * underneath it with its own page arithmetic; once that has painted, the
 * ghost goes back under and is moved on to the next neighbour. Every
 * position the reader reports, saves or selects in is therefore the live
 * paginator's, exactly as without the slide.
 *
 * The ghost has one page at a time, and the page a turn needs may be in
 * a section it has not loaded — the turn back from a chapter's first
 * page, the first turn after opening. Such a turn waits for it, briefly
 * (READY_WAIT_MS); a finger already pulling is joined by the sheet the
 * moment the page is there. Only a ghost that does not make it in that
 * time (or whose layout disagrees with the live one on the page count)
 * hands the turn back to the caller, which fades instead.
 */
import type { Book, BookSection, NavTarget, PaginatorElement } from "./core";

type Dir = 1 | -1;

/** A page of the book as the paginator counts it: text pages run from 1
 *  to pages − 2 (a blank page pads each end of a section). */
interface Target {
  index: number;
  page: number | "last";
}

export interface SlideHost {
  /** The element both paginators are layered in. */
  container: HTMLElement;
  live: PaginatorElement;
  book: Book;
  /** The injected styles, as the live paginator has them. */
  styles(): string | [string, string];
  /** Whether "next" lies to the left (see ReaderCore.advancesLeftward). */
  leftward(): boolean;
  reducedMotion(): boolean;
  /** The live paginator's own page turn. */
  turnLive(dir: Dir): Promise<void>;
  /** A turn that waited for the one before it: asked for again. */
  request(dir: Dir): void;
  /** A turn the slide cannot show after all: fade this one. */
  fallback(dir: Dir): void;
  /** The text the live paginator has on screen. */
  visible(): Range | null;
  /** A section loaded into the ghost, before it is laid out. */
  onload(detail: { doc: Document; index: number }): void;
  onoverlayer(detail: {
    doc: Document;
    index: number;
    attach: (overlayer: unknown) => void;
  }): void;
}

/** A turn made without the finger, start to end. */
const TURN_MS = 280;
/** A released drag settles in proportion to what is left of the way. */
const SETTLE_MIN_MS = 120;
const EASE_OUT = "cubic-bezier(0.25, 0.46, 0.45, 0.94)";
/** Released faster than this (px/ms) the turn follows the flick. */
const FLICK = 0.3;
/** A finger that rested this long before lifting has no velocity. */
const VELOCITY_STALE_MS = 100;
/** The still page under the sheet is dimmed at most this much. */
const DIM = 0.1;
const SHADOW = "0 0 24px rgba(0, 0, 0, 0.3)";
/** How long the ghost stays over a newly loaded section while that gets
 *  its fonts and pictures. */
const LANDING_WAIT_MS = 300;
/** How long a turn waits for a ghost that is still fetching its page
 *  (another section: an iframe load and a layout) before it fades
 *  instead. The top of what still reads as the page answering the hand —
 *  beyond a fifth of a second a reader takes the turn for missed and
 *  asks again — and several times what the load takes once the section's
 *  document is held ready (see #keepWarm). */
const READY_WAIT_MS = 200;
/** A sheet that joins a drag already under way reaches the finger over
 *  this long instead of jumping to it… */
const CATCH_UP_MS = 110;
/** …unless the finger has barely left: under this it is no jump. */
const CATCH_UP_MIN_PX = 24;
/** A step of the ghost that has not reported after this long never will
 *  (an iframe whose load event was lost): the ghost is replaced. */
const STALL_MS = 5000;
/** Near a chapter's end the next section's document is held ready this
 *  many pages ahead of the ghost needing it. */
const WARM_AHEAD_PAGES = 2;

// Stacking inside the container. The live paginator keeps its level; the
// ghost and the dim move around it.
const Z_GHOST_UNDER = "0";
const Z_DIM_UNDER = "1";
const Z_LIVE = "2";
const Z_DIM_OVER = "3";
const Z_GHOST_OVER = "4";

const LAYOUT_ATTRS = [
  "gap",
  "margin",
  "max-inline-size",
  "max-block-size",
  "max-column-count",
];

/** Resolves once a frame carrying the current state has been produced
 *  (two animation frames), or shortly after when frames are not being
 *  made at all (a hidden tab). */
function painted(): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, 150);
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        clearTimeout(timer);
        resolve();
      }),
    );
  });
}

export class CoverSlide {
  #host: SlideHost;
  #ghost: PaginatorElement | null = null;
  #dim: HTMLDivElement;
  /** idle · drag (finger down) · prepare (the ghost is stepping to its
   *  page) · settle (the animation) · commit (the live paginator is
   *  making the turn under the ghost). */
  #state: "idle" | "drag" | "prepare" | "settle" | "commit" = "idle";
  /** Bumped whenever a turn in progress is abandoned. */
  #generation = 0;
  #animations: Animation[] = [];
  /** One turn asked for while another was still under way. */
  #pending: Dir | null = null;
  /** The way the reader last turned: the neighbour kept ready. */
  #lastDir: Dir = 1;
  #background = "";

  // The ghost's navigation, one step at a time (the paginator cannot
  // take a second goTo while a section is loading).
  #want: Target | null = null;
  #pump: Promise<void> | null = null;
  /** Which ghost the pump belongs to: a ghost thrown away mid-load never
   *  finishes its step, and must not hold up the one that replaces it. */
  #pumpToken = 0;
  #busy = false;
  /** The ghost's step never reported: a new ghost at the next request. */
  #stalled = false;
  /** Gives back whatever sections the ghost still holds. */
  #release: (() => void) | null = null;
  /** Sections whose documents are held loaded for the ghost to come. */
  #warm = new Set<BookSection>();
  /** What the ghost last reported showing — for probes. */
  #shown: { index: number; range: Range | null } | null = null;

  // The drag.
  #x = 0;
  /** The way the sheet under the finger is turning; 0 while there is no
   *  sheet to move (nothing that way, or the ghost is not there yet). */
  #dragDir: Dir | 0 = 0;
  #movedAt = 0;
  /** How far the sheet stands (0..1) — behind the finger while a sheet
   *  that joined late is catching up. */
  #progress = 0;
  /** When the sheet joined a drag already under way (0: it follows 1:1). */
  #joinedAt = 0;
  #frame = 0;
  /** The ghost step a waiting drag is to be told the end of. */
  #joining: Promise<void> | null = null;

  constructor(host: SlideHost) {
    this.#host = host;
    const { container, live } = host;
    const dim = document.createElement("div");
    dim.setAttribute("aria-hidden", "true");
    Object.assign(dim.style, {
      position: "absolute",
      inset: "0",
      background: "#000",
      opacity: "0",
      pointerEvents: "none",
      zIndex: Z_DIM_UNDER,
    });
    this.#dim = dim;
    live.style.zIndex = Z_LIVE;
    container.insertBefore(dim, live);
    this.#createGhost();
  }

  /** The ghost paginator (null once destroyed). */
  get ghost(): PaginatorElement | null {
    return this.#ghost;
  }

  /** The section and visible text the ghost last settled on. */
  get shown() {
    return this.#shown;
  }

  /** A turn is under way (or a finger is on the page). */
  get busy(): boolean {
    return this.#state !== "idle";
  }

  #createGhost() {
    const { container, live, book } = this.#host;
    const ghost = document.createElement(
      "foliate-paginator",
    ) as unknown as PaginatorElement;
    ghost.setAttribute("aria-hidden", "true");
    ghost.setAttribute("data-beepub-ghost", "");
    ghost.inert = true;
    Object.assign(ghost.style, {
      position: "absolute",
      inset: "0",
      zIndex: Z_GHOST_UNDER,
      pointerEvents: "none",
      userSelect: "none",
      background: this.#background,
    });
    // What open() does, without its listener on the book: the parser
    // already rewrites stylesheets once for the live paginator.
    //
    // The sections are handed over through a tally of what this ghost
    // holds: a ghost thrown away while a section is loading never makes
    // the unload the paginator pairs with that load, and the section
    // would stay held for good.
    const holds = new Map<BookSection, number>();
    let gone = false;
    ghost.sections = book.sections.map((section) => {
      const held: BookSection = Object.create(section);
      held.load = () => {
        if (gone) return new Promise<string>(() => {});
        holds.set(section, (holds.get(section) ?? 0) + 1);
        const loading = section.load();
        // A failed load has no holders left (see shareSections).
        loading.catch(() => holds.delete(section));
        return loading;
      };
      held.unload = () => {
        const count = holds.get(section) ?? 0;
        if (gone || !count) return;
        if (count > 1) holds.set(section, count - 1);
        else holds.delete(section);
        section.unload();
      };
      return held;
    });
    this.#release = () => {
      gone = true;
      for (const [section, count] of holds)
        for (let i = 0; i < count; i++) section.unload();
      holds.clear();
    };
    ghost.bookDir = book.dir;
    ghost.setStyles(this.#host.styles());
    // Until its first section says which way it is written, the layout
    // on screen is the best guess.
    for (const attr of LAYOUT_ATTRS) {
      const value = live.getAttribute(attr);
      if (value != null) ghost.setAttribute(attr, value);
    }
    ghost.addEventListener("load", (e) =>
      this.#host.onload((e as CustomEvent).detail),
    );
    ghost.addEventListener("create-overlayer", (e) =>
      this.#host.onoverlayer((e as CustomEvent).detail),
    );
    ghost.addEventListener("relocate", (e) => {
      const { index, range } = (e as CustomEvent).detail;
      this.#shown = { index, range: range ?? null };
    });
    container.insertBefore(ghost, this.#dim);
    this.#ghost = ghost;
  }

  #destroyGhost() {
    const ghost = this.#ghost;
    if (!ghost) return;
    this.#ghost = null;
    this.#want = null;
    this.#shown = null;
    // Whatever step it was on is void (an iframe taken out of the page
    // never reports its load).
    this.#pumpToken++;
    this.#pump = null;
    this.#busy = false;
    this.#stalled = false;
    this.#joining = null;
    try {
      ghost.destroy();
    } catch (e) {
      console.warn(e);
    }
    this.#release?.();
    this.#release = null;
    ghost.remove();
  }

  /** Throw the ghost away and start a fresh one — after anything that
   *  changes how a section is read at load (the forced writing mode). */
  reset() {
    this.cancel();
    this.#destroyGhost();
    this.#createGhost();
  }

  destroy() {
    this.cancel();
    this.#destroyGhost();
    for (const section of this.#warm) section.unload();
    this.#warm.clear();
    this.#dim.remove();
    const { style } = this.#host.live;
    style.zIndex = "";
    style.background = "";
  }

  /** The page colour, behind both paginators: a sheet must hide what
   *  lies under it even where a book leaves its page transparent. */
  setBackground(color: string) {
    this.#background = color;
    this.#host.live.style.background = color;
    if (this.#ghost) this.#ghost.style.background = color;
  }

  /** Out of sight while the live page fades (a fallback turn): the page
   *  beneath a fading sheet must not be the ghost's. */
  conceal() {
    if (this.#ghost) this.#ghost.style.visibility = "hidden";
  }

  reveal() {
    if (this.#ghost) this.#ghost.style.visibility = "";
  }

  // ------------------------------------------------------------ the ghost

  #adjacent(index: number, dir: Dir): number | null {
    const { sections } = this.#host.book;
    for (let i = index + dir; i >= 0 && i < sections.length; i += dir)
      if (sections[i].linear !== "no") return i;
    return null;
  }

  /** The page one turn away from the live one (null at either end of
   *  the book, or before anything is on screen). */
  #neighbour(dir: Dir): Target | null {
    const { live } = this.#host;
    let page: number;
    let pages: number;
    let index: number | undefined;
    try {
      index = live.getContents()[0]?.index;
      page = live.page;
      pages = live.pages;
    } catch {
      return null;
    }
    if (index == null || !(pages >= 3)) return null;
    if (dir > 0) {
      if (page < pages - 2) return { index, page: page + 1 };
      const next = this.#adjacent(index, 1);
      return next == null ? null : { index: next, page: 1 };
    }
    if (page > 1) return { index, page: page - 1 };
    const prev = this.#adjacent(index, -1);
    return prev == null ? null : { index: prev, page: "last" };
  }

  #ghostIndex(): number | null {
    return this.#ghost?.getContents()[0]?.index ?? null;
  }

  /** The ghost is on `target` (whatever else is queued behind it). */
  #at(target: Target): boolean {
    const ghost = this.#ghost;
    if (!ghost || this.#ghostIndex() !== target.index) return false;
    try {
      const pages = ghost.pages;
      const page = target.page === "last" ? pages - 2 : target.page;
      if (ghost.page !== page) return false;
      // The same section as the live one: unless the two layouts agree
      // on the page count, the ghost's page is not the neighbour.
      const live = this.#host.live;
      if (live.getContents()[0]?.index === target.index && live.pages !== pages)
        return false;
      return true;
    } catch {
      return false;
    }
  }

  /** The ghost shows `target`, settled. */
  #ready(target: Target): boolean {
    return !this.#busy && this.#at(target);
  }

  /** Ask the ghost for `target`. Requests collapse: only the latest one
   *  still wanted when the paginator is free is made. */
  #show(target: Target): Promise<void> {
    if (this.#stalled) {
      // The step that never reported still has the paginator: a fresh
      // ghost takes the request.
      this.#destroyGhost();
      this.#createGhost();
    }
    this.#want = target;
    if (!this.#pump) {
      const token = this.#pumpToken;
      this.#busy = true;
      const pump = this.#drain(token).finally(() => {
        if (this.#pump === pump) this.#pump = null;
      });
      this.#pump = pump;
    }
    return this.#pump;
  }

  async #drain(token: number) {
    try {
      for (;;) {
        if (token !== this.#pumpToken) return;
        const ghost = this.#ghost;
        const target = this.#want;
        this.#want = null;
        if (!ghost || !target) return;
        if (this.#at(target)) continue;
        const loads = this.#ghostIndex() !== target.index;
        const nav: NavTarget = {
          index: target.index,
          // A fraction, read off the ghost's own page count once the
          // section is laid out: the paginator rounds it back to the page.
          anchor: () => {
            if (target.page === "last") return 1;
            const textPages = ghost.pages - 2;
            return textPages > 1 ? (target.page - 1) / (textPages - 1) : 0;
          },
        };
        let timer: ReturnType<typeof setTimeout> | undefined;
        const stalled = await Promise.race([
          ghost.goTo(nav).then(
            () => false,
            (e) => {
              console.warn(e);
              return false;
            },
          ),
          new Promise<boolean>((resolve) => {
            timer = setTimeout(() => resolve(true), STALL_MS);
          }),
        ]);
        clearTimeout(timer);
        if (token !== this.#pumpToken) return;
        if (stalled) {
          console.warn(
            new Error(`The slide's page for ${target.index} stalled`),
          );
          this.#stalled = true;
          return;
        }
        if (loads) {
          // A section just loaded is laid out once more within a frame
          // or two (the observers on its body, its fonts), and the page
          // count can change with it: let that pass, then look whether
          // the ghost is still on the page asked for. A turn must not
          // start on a page that is about to shift.
          await painted();
          if (token !== this.#pumpToken) return;
          this.#want ??= target;
        }
      }
    } finally {
      if (token === this.#pumpToken) this.#busy = false;
    }
  }

  /** Ask the ghost for `target` and say whether it has it — at once
   *  within the section it is in, after a load otherwise, and not at all
   *  past READY_WAIT_MS (or once the turn `generation` has been
   *  abandoned). */
  async #awaitReady(target: Target, generation: number): Promise<boolean> {
    const deadline = performance.now() + READY_WAIT_MS;
    const sleep = (ms: number) =>
      new Promise<void>((resolve) => setTimeout(resolve, ms));
    let misses = 0;
    for (;;) {
      const left = deadline - performance.now();
      await Promise.race([this.#show(target), sleep(Math.max(0, left))]);
      if (generation !== this.#generation) return false;
      if (this.#ready(target)) return true;
      if (performance.now() >= deadline || this.#stalled) return false;
      // The step is over without the page: the two layouts disagree on
      // the page count. Right after a relayout that passes within a
      // frame; a disagreement that stays is not worth the whole wait.
      if (!this.#busy && ++misses >= 3) return false;
      await Promise.race([painted(), sleep(Math.max(0, left))]);
      if (generation !== this.#generation) return false;
    }
  }

  /** Keep the neighbour in the reading direction ready. */
  #sync() {
    if (!this.#ghost || this.#state !== "idle") return;
    if (this.#host.reducedMotion()) return;
    const target =
      this.#neighbour(this.#lastDir) ??
      this.#neighbour(this.#lastDir > 0 ? -1 : 1);
    if (target) void this.#show(target);
    this.#keepWarm();
  }

  /**
   * The ghost shows one page, the one ahead; a turn the other way out of
   * a chapter's first (or last) page needs another section in it. What
   * can be had beforehand without moving the ghost is that section's
   * document: loaded here, the parser's share of the work (reading the
   * markup, rewriting its links, minting its resources) is done when the
   * ghost asks, and only the iframe's load and the layout are left for
   * the turn to wait on. The same for the section ahead, a couple of
   * pages before the ghost gets to it, for a reader paging quickly.
   *
   * Loads and unloads are the counted ones (shareSections), so a section
   * held here and by a paginator is loaded once and unloaded when the
   * last of them lets go. At most two sections, and only near a chapter
   * boundary.
   */
  #keepWarm() {
    const { live, book } = this.#host;
    const wanted = new Set<BookSection>();
    let index: number | undefined;
    try {
      index = live.getContents()[0]?.index;
      if (index != null && live.pages >= 3) {
        const behind = this.#neighbour(this.#lastDir > 0 ? -1 : 1);
        if (behind && behind.index !== index)
          wanted.add(book.sections[behind.index]);
        const toEdge =
          this.#lastDir > 0 ? live.pages - 2 - live.page : live.page - 1;
        const ahead = this.#adjacent(index, this.#lastDir);
        if (ahead != null && toEdge <= WARM_AHEAD_PAGES)
          wanted.add(book.sections[ahead]);
      }
    } catch {
      // nothing on screen yet
    }
    for (const section of wanted) {
      if (this.#warm.has(section)) continue;
      this.#warm.add(section);
      // A failed load has no holders left: nothing of ours to unload.
      section.load().catch(() => this.#warm.delete(section));
    }
    for (const section of Array.from(this.#warm)) {
      if (wanted.has(section)) continue;
      this.#warm.delete(section);
      section.unload();
    }
  }

  /** The live paginator settled on a page (a turn, a jump, a relayout). */
  relocated() {
    // Also in the middle of a turn, when the ghost itself is not moved:
    // a reader paging quickly is the one about to need the next section.
    if (this.#ghost && !this.#host.reducedMotion()) this.#keepWarm();
    this.#sync();
  }

  // ----------------------------------------------------------- the layers

  #width(): number {
    return this.#host.container.clientWidth || 1;
  }

  /** Where the moving sheet is at progress `p` (0 = the turn has not
   *  begun, 1 = it is complete). Next: the live page leaves toward the
   *  side "previous" lies on. Previous: the ghost comes in from there. */
  #transform(dir: Dir, p: number): string {
    const side = this.#host.leftward() ? 1 : -1;
    const x = side * (dir > 0 ? p : 1 - p) * this.#width();
    return `translate3d(${x}px, 0, 0)`;
  }

  /** The still page darkens as it is covered, clears as it is bared. */
  #dimOpacity(dir: Dir, p: number): string {
    return String(DIM * (dir > 0 ? 1 - p : p));
  }

  #arrange(dir: Dir, p: number) {
    const ghost = this.#ghost;
    if (!ghost) return;
    const live = this.#host.live;
    const dim = this.#dim;
    ghost.style.visibility = "";
    dim.style.opacity = this.#dimOpacity(dir, p);
    if (dir > 0) {
      ghost.style.zIndex = Z_GHOST_UNDER;
      ghost.style.transform = "";
      ghost.style.boxShadow = "";
      ghost.style.willChange = "";
      dim.style.zIndex = Z_DIM_UNDER;
      live.style.transform = this.#transform(dir, p);
      live.style.boxShadow = SHADOW;
      live.style.willChange = "transform";
    } else {
      live.style.transform = "";
      live.style.boxShadow = "";
      live.style.willChange = "";
      dim.style.zIndex = Z_DIM_OVER;
      ghost.style.zIndex = Z_GHOST_OVER;
      ghost.style.transform = this.#transform(dir, p);
      ghost.style.boxShadow = SHADOW;
      ghost.style.willChange = "transform";
    }
  }

  /** Both sheets flat, `ghostZ` deciding which one is seen. */
  #flatten(ghostZ: string) {
    const live = this.#host.live;
    for (const el of [live, this.#ghost]) {
      if (!el) continue;
      el.style.transform = "";
      el.style.boxShadow = "";
      el.style.willChange = "";
    }
    if (this.#ghost) this.#ghost.style.zIndex = ghostZ;
    this.#dim.style.opacity = "0";
    this.#dim.style.zIndex = Z_DIM_UNDER;
  }

  /** The resting arrangement: the live page on top, the ghost under it. */
  #rest() {
    this.#flatten(Z_GHOST_UNDER);
    this.#host.live.style.pointerEvents = "";
    this.#state = "idle";
    this.#dragDir = 0;
    this.#x = 0;
    this.#progress = 0;
    this.#joining = null;
    this.#stopCatchUp();
  }

  #stopCatchUp() {
    this.#joinedAt = 0;
    if (this.#frame) cancelAnimationFrame(this.#frame);
    this.#frame = 0;
  }

  async #animate(dir: Dir, from: number, to: number, ms: number) {
    const mover = dir > 0 ? this.#host.live : this.#ghost;
    if (!mover || typeof mover.animate !== "function") return;
    const options = { duration: ms, easing: EASE_OUT };
    const animations = [
      mover.animate(
        [
          { transform: this.#transform(dir, from) },
          { transform: this.#transform(dir, to) },
        ],
        options,
      ),
      this.#dim.animate(
        [
          { opacity: this.#dimOpacity(dir, from) },
          { opacity: this.#dimOpacity(dir, to) },
        ],
        options,
      ),
    ];
    this.#animations = animations;
    // A tab in the background does not run animations; the turn must
    // still end.
    const guard = setTimeout(() => this.#finishAnimations(), ms + 150);
    await Promise.all(animations.map((a) => a.finished.catch(() => {})));
    clearTimeout(guard);
    if (this.#animations === animations) this.#animations = [];
  }

  #finishAnimations() {
    for (const a of this.#animations) {
      try {
        a.finish();
      } catch {
        // already over
      }
    }
  }

  /** Slide from `from` to `to` (1 = the turn is made, 0 = back where it
   *  started), then make the turn for real or settle back. */
  async #run(dir: Dir, from: number, to: 0 | 1, ms: number) {
    const generation = this.#generation;
    this.#state = "settle";
    // A tap during the slide belongs to the reader's margins, not to a
    // page that is on its way out.
    this.#host.live.style.pointerEvents = "none";
    // The end state stands in the styles; the animation plays over it.
    this.#arrange(dir, to);
    if (from !== to) await this.#animate(dir, from, to, ms);
    if (generation !== this.#generation) return;
    if (to === 0) {
      this.#rest();
      this.#afterTurn();
      return;
    }
    // The ghost covers the live paginator while that makes the same
    // turn underneath: nothing changes on screen.
    this.#state = "commit";
    this.#lastDir = dir;
    this.#flatten(Z_GHOST_OVER);
    const live = this.#host.live;
    const doc = live.getContents()[0]?.doc;
    try {
      await this.#host.turnLive(dir);
    } catch (e) {
      console.warn(e);
    }
    if (generation !== this.#generation) return;
    // A turn into another section put a new document under the ghost:
    // its fonts and the pictures on its page first.
    const landed = live.getContents()[0]?.doc;
    if (landed && landed !== doc) await this.#drawn(landed);
    if (generation !== this.#generation) return;
    // Under the ghost until its new page has been painted.
    await painted();
    if (generation !== this.#generation) return;
    this.#rest();
    this.#afterTurn();
  }

  /** A freshly loaded live document has what its page needs to look as
   *  the ghost does: its fonts in, the pictures on the page decoded.
   *  Bounded — a slow font must not keep the reader behind the ghost. */
  #drawn(doc: Document): Promise<unknown> {
    const waits: Promise<unknown>[] = [];
    if (doc.fonts?.status === "loading") waits.push(doc.fonts.ready);
    const visible = this.#host.visible();
    for (const img of Array.from(doc.querySelectorAll("img"))) {
      if (img.complete || typeof img.decode !== "function") continue;
      try {
        if (visible && !visible.intersectsNode(img)) continue;
      } catch {
        // a range of another document: wait for the picture anyway
      }
      waits.push(img.decode().catch(() => {}));
    }
    if (!waits.length) return Promise.resolve();
    return Promise.race([
      Promise.allSettled(waits),
      new Promise((resolve) => setTimeout(resolve, LANDING_WAIT_MS)),
    ]);
  }

  #afterTurn() {
    const pending = this.#pending;
    this.#pending = null;
    if (pending) this.#host.request(pending);
    else this.#sync();
  }

  /** Abandon whatever is in progress: both sheets flat, the live one on
   *  top. For navigation, which is not a page turn. */
  cancel() {
    this.#generation++;
    this.#pending = null;
    const animations = this.#animations;
    this.#animations = [];
    for (const a of animations) a.cancel();
    if (this.#state !== "idle") this.#rest();
  }

  // ---------------------------------------------------------------- turns

  /**
   * A page turn without the finger (tap zone, key, wheel, toolbar).
   * Returns false when there is nothing to slide to; a turn taken here
   * that the ghost then fails to show goes back through `fallback`.
   *
   * A turn asked for while another is still sliding ends that slide at
   * once and follows it; at most one waits, so quick paging keeps pace
   * and never builds a backlog.
   */
  turn(dir: Dir): boolean {
    if (!this.#ghost) return false;
    switch (this.#state) {
      case "drag":
        return true; // a finger is on the page
      case "settle":
        this.#pending = dir;
        this.#finishAnimations();
        return true;
      case "prepare":
      case "commit":
        this.#pending = dir;
        return true;
    }
    const target = this.#neighbour(dir);
    if (!target) return false;
    this.#begin(dir, target);
    return true;
  }

  /** Play the turn to `target` from rest, as soon as the ghost has the
   *  page: at once within its section, after a short wait when it has to
   *  load another. A ghost that does not make it hands the turn back. */
  #begin(dir: Dir, target: Target) {
    // Whatever becomes of this turn, the reader is going this way: the
    // ghost waits on that side afterwards.
    this.#lastDir = dir;
    const generation = this.#generation;
    this.#state = "prepare";
    void this.#awaitReady(target, generation).then((ready) => {
      if (generation !== this.#generation || this.#state !== "prepare") return;
      if (!ready) {
        this.#state = "idle";
        this.#pending = null;
        this.#host.fallback(dir);
        return;
      }
      void this.#run(dir, 0, 1, TURN_MS);
    });
  }

  /**
   * The finger moved by (previous − current) px along the screen's x
   * axis. Returns whether the slide has the gesture. Toward the end of
   * the book nothing moves; toward a page the ghost does not have yet
   * (another section) nothing moves until it has, and then the sheet
   * joins the finger where it is by now.
   */
  dragBy(dx: number): boolean {
    if (!this.#ghost || this.#host.reducedMotion()) return false;
    if (this.#state === "idle") {
      this.#state = "drag";
      this.#x = 0;
      this.#dragDir = 0;
      this.#progress = 0;
    } else if (this.#state !== "drag") return false;
    this.#x -= dx;
    this.#movedAt = performance.now();
    this.#follow(false);
    return true;
  }

  /** The way the finger has pulled so far. */
  #pull(): Dir | 0 {
    const p = (this.#host.leftward() ? 1 : -1) * this.#x;
    return p > 0 ? 1 : p < 0 ? -1 : 0;
  }

  /** Put the sheet where the finger is — or, while the ghost does not
   *  have the page it is pulling toward, send for it. `joining`: the
   *  ghost has just finished a step this drag was waiting on. */
  #follow(joining: boolean) {
    const dir = this.#pull();
    const target = dir ? this.#neighbour(dir) : null;
    if (!dir || !target || !this.#ready(target)) {
      if (this.#dragDir) this.#flatten(Z_GHOST_UNDER);
      this.#dragDir = 0;
      this.#progress = 0;
      this.#stopCatchUp();
      if (!dir || !target) return;
      this.#lastDir = dir;
      // (A step that ended without the page — the two layouts disagree —
      // is not asked for again until the finger moves.)
      if (joining) return;
      const step = this.#show(target);
      if (this.#joining === step) return;
      this.#joining = step;
      void step.then(() => {
        if (this.#joining !== step) return;
        this.#joining = null;
        if (this.#state === "drag" && !this.#dragDir) this.#follow(true);
      });
      return;
    }
    if (this.#dragDir !== dir) {
      this.#dragDir = dir;
      this.#joining = null;
      // The sheet appears under a finger that is already some way off:
      // it runs up to it rather than jump.
      this.#stopCatchUp();
      if (Math.abs(this.#x) > CATCH_UP_MIN_PX)
        this.#joinedAt = performance.now();
    }
    this.#paint();
  }

  #paint() {
    const dir = this.#dragDir;
    if (!dir) return;
    let p = Math.min(1, Math.abs(this.#x) / this.#width());
    if (this.#joinedAt) {
      const t = (performance.now() - this.#joinedAt) / CATCH_UP_MS;
      if (t >= 1) this.#joinedAt = 0;
      // Ease-out toward wherever the finger is by now.
      else p *= 1 - (1 - t) ** 3;
    }
    this.#progress = p;
    this.#arrange(dir, p);
    if (this.#joinedAt && !this.#frame)
      this.#frame = requestAnimationFrame(() => {
        this.#frame = 0;
        if (this.#state === "drag") this.#paint();
      });
  }

  /** Whether a release `p` of the way across, moving at `vx`, makes the
   *  turn `dir`. */
  #completes(dir: Dir, p: number, vx: number): boolean {
    const side = this.#host.leftward() ? 1 : -1;
    const stale = performance.now() - this.#movedAt > VELOCITY_STALE_MS;
    // Velocity toward completing the turn.
    const toward = stale || !Number.isFinite(vx) ? 0 : side * -vx * dir;
    return toward > FLICK || (p > 0.5 && toward > -FLICK);
  }

  /**
   * The finger lifted, moving at `vx` px/ms (previous − current). How far
   * it has come and how fast it was going decide between making the turn
   * and springing back. Returns false when there was no page to pull
   * toward (the end of the book): the caller treats the gesture as a
   * plain swipe.
   *
   * A finger that lifts before the ghost has the page is judged the same
   * way, and its turn played from rest once the page is there.
   */
  dragEnd(vx: number): boolean {
    if (this.#state !== "drag") return false;
    const p = Math.min(1, Math.abs(this.#x / this.#width()));
    const dir = this.#dragDir;
    if (!dir) {
      const pulled = this.#pull();
      const target = pulled ? this.#neighbour(pulled) : null;
      const complete = !!pulled && this.#completes(pulled, p, vx);
      this.#rest();
      if (!pulled || !target) return false;
      if (complete) this.#begin(pulled, target);
      else this.#afterTurn();
      return true;
    }
    const complete = this.#completes(dir, p, vx);
    // From where the sheet stands, which is short of the finger while it
    // is still catching up.
    const from = this.#progress;
    this.#stopCatchUp();
    const left = complete ? 1 - from : from;
    const ms = Math.max(SETTLE_MIN_MS, Math.round(TURN_MS * left));
    void this.#run(dir, from, complete ? 1 : 0, ms);
    return true;
  }

  /** The touch ended without a release (cancelled, or a new one began):
   *  a sheet left displaced springs back. */
  dragCancel() {
    if (this.#state !== "drag") return;
    const dir = this.#dragDir;
    if (!dir) {
      this.#rest();
      return;
    }
    const from = this.#progress;
    this.#stopCatchUp();
    void this.#run(dir, from, 0, SETTLE_MIN_MS);
  }
}
