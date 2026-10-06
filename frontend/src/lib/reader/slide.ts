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
 * keeps further paginators — the ghosts — on the pages one turn away.
 * A ghost is a full paginator fed the same styles, layout parameters and
 * per-section adjustments as the live one, so the page it shows is laid
 * out by the same code from the same inputs; it is inert (no pointer
 * events, no focus, no listeners of the reader's) and never reported by
 * the core as a section on screen.
 *
 * A ghost holds a section, and steps about inside it for nothing (a
 * scroll). What costs is putting a section into one: an iframe load and
 * the layout of the whole chapter. So there is a ghost for every section
 * within reach, and no more: in the middle of a chapter one, on the page
 * ahead; within a few pages of a chapter's edge a second one, built in
 * the background, holding the neighbouring chapter on its first (or
 * last) page; a third only in a chapter so short that both its edges are
 * near. A turn across a chapter boundary then finds its page rendered,
 * and the ghost it leaves behind stays in the chapter just left, ready
 * for the turn back. The far ghost is given up again once the reader is
 * well inside a chapter.
 *
 * Only a layer's horizontal transform animates. How the paginator stacks
 * a section's pages internally (side by side, or top to bottom for
 * vertical text) does not matter, which is what lets vertical books
 * slide.
 *
 * A ghost never becomes the live page. A completed turn ends with the
 * ghost lying over the live paginator — the cover — while that makes the
 * same turn underneath with its own page arithmetic; once the live page
 * has painted, the cover goes back under. Every position the reader
 * reports, saves or selects in is therefore the live paginator's, exactly
 * as without the slide.
 *
 * The live paginator's turn into another chapter is a load — the whole
 * chapter laid out, with the page's own thread busy for as long — and
 * the reader does not wait for it: while the cover is up, the page the
 * reader is on is the cover's, and the next turn is played from there —
 * the cover is the sheet that slides away, or the one slid over — as
 * long as another ghost has the page it goes to. The live paginator is
 * owed those turns. A turn within its section it makes at once; one
 * into another chapter it puts off until the reader has stayed on the
 * page a moment (DWELL_MS), so that leafing back and forth over a
 * chapter boundary moves two ghosts and loads nothing, and two turns
 * that undo each other are never made at all. A turn whose page only
 * the cover itself could show has the live paginator catch up first.
 *
 * A page no ghost has (a jump into a chapter's edge, the first turn
 * after opening) is waited for, briefly (READY_WAIT_MS); a finger already
 * pulling is joined by the sheet the moment the page is there. Only a
 * ghost that does not make it in that time (or whose layout disagrees
 * with the live one on the page count) hands the turn back to the
 * caller, which fades instead.
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
  /** The element the paginators are layered in. */
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
  /** A section loaded into a ghost, before it is laid out. */
  onload(
    detail: { doc: Document; index: number },
    ghost: PaginatorElement,
  ): void;
  onoverlayer(
    detail: {
      doc: Document;
      index: number;
      attach: (overlayer: unknown) => void;
    },
    ghost: PaginatorElement,
  ): void;
  /** A ghost was taken down. */
  ongone(ghost: PaginatorElement): void;
}

/** What became of a turn, for probes and tests: it slid, sprang back
 *  under a released finger, or was handed to the fade (and why: the page
 *  did not come in time, the two layouts disagreed on the page count, the
 *  ghost had stalled) — and the sections put into ghosts, with how long
 *  each took. */
export type SlideEvent =
  | { at: number; dir: Dir; how: "slide" | "spring" }
  | { at: number; dir: Dir; how: "fade"; why: "wait" | "pages" | "stall" }
  | { at: number; load: number; ms: number };

/** A turn made without the finger, start to end. */
const TURN_MS = 280;
/** A released drag settles in proportion to what is left of the way. */
const SETTLE_MIN_MS = 120;
const EASE_OUT = "cubic-bezier(0.25, 0.46, 0.45, 0.94)";
/** Released faster than this (px/ms) the turn follows the flick. */
const FLICK = 0.3;
/** A finger that rested this long before lifting has no velocity. */
const VELOCITY_STALE_MS = 100;
/** A swipe no sheet followed turns the page past this distance (the
 *  gesture layer's own threshold). */
const SWIPE_PX = 50;
/** The still page under the sheet is dimmed at most this much. */
const DIM = 0.1;
const SHADOW = "0 0 24px rgba(0, 0, 0, 0.3)";
/** How long the cover stays over a newly loaded section while that gets
 *  its fonts and pictures. */
const LANDING_WAIT_MS = 300;
/** How long a turn waits for a ghost that is still fetching its page
 *  (another section: an iframe load and a layout) before it fades
 *  instead. The top of what still reads as the page answering the hand —
 *  beyond a fifth of a second a reader takes the turn for missed and
 *  asks again. */
const READY_WAIT_MS = 200;
/** A sheet that joins a drag already under way reaches the finger over
 *  this long instead of jumping to it… */
const CATCH_UP_MS = 110;
/** …unless the finger has barely left: under this it is no jump. */
const CATCH_UP_MIN_PX = 24;
/** A sheet that joined a drag less than this before the finger lifted
 *  was hardly seen: the release is a plain swipe's. */
const SEEN_MS = CATCH_UP_MS + 90;
/** How long the reader has to stay on a page reached across a chapter
 *  boundary before the live paginator loads that chapter under the
 *  cover. Longer than the gap between two turns of someone leafing back
 *  and forth; short of the time it takes to begin reading the page (the
 *  page under a cover takes no selection and follows no link). */
const DWELL_MS = 300;
/** A step of a ghost that has not reported after this long never will
 *  (an iframe whose load event was lost): the ghost is replaced. */
const STALL_MS = 5000;
/** The neighbouring chapter gets its ghost this many pages before the
 *  boundary… */
const NEAR_PAGES = 3;
/** …and keeps it until the reader is this far past it again (pacing
 *  about the first distance must not build and drop a chapter each
 *  time). */
const KEEP_PAGES = 6;
/** A jump reports several positions on its way (the new section's
 *  first page, then the place in it): the ghosts are arranged for the
 *  one it stays on. */
const RELOCATE_SETTLE_MS = 60;
/** The live section, and one on either side of it. */
const MAX_GHOSTS = 3;
const LOG_SIZE = 200;

// Stacking inside the container. The live paginator keeps its level; the
// ghosts and the dim move around it.
const Z_IDLE = "0";
const Z_UNDER = "1";
const Z_DIM_UNDER = "2";
const Z_LIVE = "3";
const Z_COVER = "4";
const Z_DIM_OVER = "5";
const Z_OVER = "6";

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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

function flatten(el: HTMLElement) {
  el.style.transform = "";
  el.style.boxShadow = "";
  el.style.willChange = "";
}

/**
 * One inert rendering and its navigation, a step at a time (the
 * paginator cannot take a second goTo while a section is loading).
 */
class Ghost {
  readonly el: PaginatorElement;
  /** The section it is in, or on its way to. */
  section: number | null = null;
  /** What it last reported showing — for probes. */
  shown: { index: number; range: Range | null } | null = null;
  /** A step is under way. */
  busy = false;
  /** A step never reported: the ghost is to be replaced. */
  stalled = false;

  #want: Target | null = null;
  #pump: Promise<void> | null = null;
  #gone = false;
  /** Its element has been in the page for a frame (see planted). */
  #rooted: Promise<void> | null = null;
  /** Gives back whatever sections it still holds. */
  #release: () => void;
  /** Whether a page count of `index` is the live paginator's too. */
  #agrees: (index: number, pages: number) => boolean;
  #loaded: (index: number, ms: number) => void;

  constructor(
    host: SlideHost,
    background: string,
    agrees: (index: number, pages: number) => boolean,
    loaded: (index: number, ms: number) => void,
  ) {
    this.#agrees = agrees;
    this.#loaded = loaded;
    const { live, book } = host;
    const el = document.createElement(
      "foliate-paginator",
    ) as unknown as PaginatorElement;
    el.setAttribute("aria-hidden", "true");
    el.setAttribute("data-beepub-ghost", "");
    el.inert = true;
    Object.assign(el.style, {
      position: "absolute",
      inset: "0",
      zIndex: Z_IDLE,
      pointerEvents: "none",
      userSelect: "none",
      background,
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
    el.sections = book.sections.map((section) => {
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
    el.bookDir = book.dir;
    el.setStyles(host.styles());
    // Until its first section says which way it is written, the layout
    // on screen is the best guess.
    for (const attr of LAYOUT_ATTRS) {
      const value = live.getAttribute(attr);
      if (value != null) el.setAttribute(attr, value);
    }
    el.addEventListener("load", (e) =>
      host.onload((e as CustomEvent).detail, el),
    );
    el.addEventListener("create-overlayer", (e) =>
      host.onoverlayer((e as CustomEvent).detail, el),
    );
    el.addEventListener("relocate", (e) => {
      const { index, range } = (e as CustomEvent).detail;
      this.shown = { index, range: range ?? null };
    });
    this.el = el;
  }

  /**
   * The element has just been put into the page. A paginator asked for
   * a section before it has been laid out itself (and its own observers
   * have reported its size) renders that section two or three times
   * over, the first of them with a geometry that takes several times as
   * long as the real one: its first step waits for a frame.
   */
  planted() {
    this.#rooted = painted();
  }

  /** The section loaded in it. */
  get index(): number | null {
    try {
      return this.el.getContents()[0]?.index ?? null;
    } catch {
      return null;
    }
  }

  /** Where it stands, as the paginator counts. */
  position(): { index: number; page: number; pages: number } | null {
    const index = this.index;
    if (index == null) return null;
    try {
      return { index, page: this.el.page, pages: this.el.pages };
    } catch {
      return null;
    }
  }

  /** It is on `target` (whatever else is queued behind it). */
  at(target: Target): boolean {
    if (this.#gone || this.index !== target.index) return false;
    try {
      const pages = this.el.pages;
      const page = target.page === "last" ? pages - 2 : target.page;
      if (this.el.page !== page) return false;
      // The same section as the live one: unless the two layouts agree
      // on the page count, this page is not the neighbour.
      return this.#agrees(target.index, pages);
    } catch {
      return false;
    }
  }

  /** It shows `target`, settled. */
  ready(target: Target): boolean {
    return !this.busy && this.at(target);
  }

  /** Ask for `target`. Requests collapse: only the latest one still
   *  wanted when the paginator is free is made. */
  show(target: Target): Promise<void> {
    if (this.#gone) return Promise.resolve();
    this.section = target.index;
    if (!this.#pump) {
      if (this.at(target)) return Promise.resolve();
      this.#want = target;
      this.busy = true;
      const pump = this.#drain().finally(() => {
        if (this.#pump === pump) this.#pump = null;
      });
      this.#pump = pump;
    } else this.#want = target;
    return this.#pump;
  }

  async #drain() {
    const ghost = this.el;
    try {
      if (this.#rooted) {
        await this.#rooted;
        this.#rooted = null;
      }
      for (;;) {
        if (this.#gone) return;
        const target = this.#want;
        this.#want = null;
        if (!target) return;
        if (this.at(target)) continue;
        const loads = this.index !== target.index;
        const started = performance.now();
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
        if (this.#gone) return;
        if (stalled) {
          console.warn(
            new Error(`The slide's page for ${target.index} stalled`),
          );
          this.stalled = true;
          return;
        }
        if (loads) {
          // A section just loaded is laid out once more within a frame
          // or two (the observers on its body, its fonts), and the page
          // count can change with it: let that pass, then look whether
          // the ghost is still on the page asked for. A turn must not
          // start on a page that is about to shift.
          await painted();
          if (this.#gone) return;
          this.#loaded(target.index, Math.round(performance.now() - started));
          this.#want ??= target;
        }
      }
    } finally {
      this.busy = false;
    }
  }

  destroy() {
    if (this.#gone) return;
    this.#gone = true;
    this.#want = null;
    try {
      this.el.destroy();
    } catch (e) {
      console.warn(e);
    }
    this.#release();
    this.el.remove();
  }
}

export class CoverSlide {
  #host: SlideHost;
  #enabled = true;
  #ghosts: Ghost[] = [];
  #dim: HTMLDivElement;
  /** idle · drag (a sheet is the finger's) · prepare (a ghost is
   *  stepping to the page a turn needs) · settle (the animation). */
  #state: "idle" | "drag" | "prepare" | "settle" = "idle";
  /** The ghost lying over the live paginator, showing the page the
   *  reader is on, until the live one has made the turns it is owed. */
  #cover: Ghost | null = null;
  /** The ghost taking part in the turn (or drag) under way. */
  #partner: Ghost | null = null;
  /** Turns played on the sheets that the live paginator has not begun. */
  #owed = 0;
  /** The live paginator is making them. */
  #chasing = false;
  /** …or will, once the reader has stayed on the page this long. */
  #dwell: ReturnType<typeof setTimeout> | null = null;
  /** Bumped whenever everything in progress is abandoned. */
  #generation = 0;
  #animations: Animation[] = [];
  /** One turn asked for while it could not be played yet. */
  #pending: Dir | null = null;
  /** The way the reader last turned: the neighbour kept ready first. */
  #lastDir: Dir = 1;
  #background = "";
  #concealed = false;
  #relocating: ReturnType<typeof setTimeout> | null = null;
  #log: SlideEvent[] = [];

  // The finger.
  /** A swipe is on its way (whether or not a sheet follows it). */
  #finger = false;
  /** How far it has come, along the screen's x axis. */
  #x = 0;
  #movedAt = 0;
  /** The way the sheet under the finger is turning; 0 while there is no
   *  sheet to move (nothing that way, or its page is not there yet). */
  #dragDir: Dir | 0 = 0;
  /** How far the sheet stands (0..1) — behind the finger while a sheet
   *  that joined late is catching up. */
  #progress = 0;
  /** When the sheet joined a drag already under way (0: it follows 1:1). */
  #joinedAt = 0;
  /** …kept for the release: a sheet that had only just come was not
   *  what the reader let go of. */
  #lateAt = 0;
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
  }

  /** The ghost a probe most likely means: the one in the turn under
   *  way, else the cover, else the one on the page ahead (null when
   *  there is none). */
  get ghost(): PaginatorElement | null {
    return this.#principal()?.el ?? null;
  }

  /** The section and visible text that ghost last settled on. */
  get shown() {
    return this.#principal()?.shown ?? null;
  }

  /** Every ghost there is. */
  get ghosts(): PaginatorElement[] {
    return this.#ghosts.map((g) => g.el);
  }

  /** The ghost holding the section of the page one turn away in `dir`
   *  (on that page or still on its way there). */
  ghostFor(dir: Dir): PaginatorElement | null {
    const target = this.#neighbour(dir);
    if (!target) return null;
    return this.#ghosts.find((g) => g.section === target.index)?.el ?? null;
  }

  /** What became of the last turns (see SlideEvent). */
  get log(): SlideEvent[] {
    return this.#log;
  }

  /** A turn is under way, a finger is on the page, or the live
   *  paginator is still catching up under the cover. */
  get busy(): boolean {
    return this.#state !== "idle" || !!this.#cover;
  }

  #principal(): Ghost | null {
    if (this.#partner) return this.#partner;
    if (this.#cover) return this.#cover;
    const target =
      this.#neighbour(this.#lastDir) ??
      this.#neighbour(this.#lastDir > 0 ? -1 : 1);
    const holder = target
      ? this.#ghosts.find((g) => g.section === target.index)
      : null;
    return holder ?? this.#ghosts[0] ?? null;
  }

  #note(event: SlideEvent) {
    this.#log.push(event);
    if (this.#log.length > LOG_SIZE) this.#log.shift();
  }

  #now(): number {
    return Math.round(performance.now());
  }

  // ----------------------------------------------------------- the ghosts

  #spawn(): Ghost {
    const { container, live } = this.#host;
    const ghost = new Ghost(
      this.#host,
      this.#background,
      (index, pages) => {
        // The live layout is the one a page count has to agree with.
        try {
          return live.getContents()[0]?.index !== index || live.pages === pages;
        } catch {
          return true;
        }
      },
      (index, ms) => this.#note({ at: this.#now(), load: index, ms }),
    );
    if (this.#concealed) ghost.el.style.visibility = "hidden";
    container.insertBefore(ghost.el, this.#dim);
    ghost.planted();
    this.#ghosts.push(ghost);
    return ghost;
  }

  #drop(ghost: Ghost) {
    const at = this.#ghosts.indexOf(ghost);
    if (at >= 0) this.#ghosts.splice(at, 1);
    if (this.#cover === ghost) this.#cover = null;
    if (this.#partner === ghost) this.#partner = null;
    ghost.destroy();
    this.#host.ongone(ghost.el);
  }

  #dropAll() {
    for (const ghost of Array.from(this.#ghosts)) this.#drop(ghost);
  }

  /** Part of what is on screen right now: not to be moved or dropped. */
  #engaged(ghost: Ghost): boolean {
    return ghost === this.#cover || ghost === this.#partner;
  }

  /** Throw the ghosts away — after anything that changes how a section
   *  is read at load (the forced writing mode). Fresh ones follow the
   *  page the reader lands on. */
  reset() {
    this.cancel();
    this.#dropAll();
  }

  destroy() {
    this.cancel();
    this.#enabled = false;
    if (this.#relocating != null) clearTimeout(this.#relocating);
    this.#relocating = null;
    this.#dropAll();
    this.#dim.remove();
    const { style } = this.#host.live;
    style.zIndex = "";
    style.background = "";
  }

  /** The page colour, behind every paginator: a sheet must hide what
   *  lies under it even where a book leaves its page transparent. */
  setBackground(color: string) {
    this.#background = color;
    this.#host.live.style.background = color;
    for (const ghost of this.#ghosts) ghost.el.style.background = color;
  }

  /** The injected styles changed. */
  setStyles(styles: string | [string, string]) {
    for (const ghost of this.#ghosts) ghost.el.setStyles(styles);
  }

  /** Out of sight while the live page fades (a fallback turn): the page
   *  beneath a fading sheet must not be a ghost's. */
  conceal() {
    this.#concealed = true;
    for (const ghost of this.#ghosts) ghost.el.style.visibility = "hidden";
  }

  reveal() {
    this.#concealed = false;
    for (const ghost of this.#ghosts) ghost.el.style.visibility = "";
  }

  #adjacent(index: number, dir: Dir): number | null {
    const { sections } = this.#host.book;
    for (let i = index + dir; i >= 0 && i < sections.length; i += dir)
      if (sections[i].linear !== "no") return i;
    return null;
  }

  /** The page the reader is on: the cover's while one is up (the live
   *  paginator is still on its way there), else the live one's. Null
   *  before anything is on screen. */
  #here(): { index: number; page: number; pages: number } | null {
    if (this.#cover) return this.#cover.position();
    const { live } = this.#host;
    try {
      const index = live.getContents()[0]?.index;
      const pages = live.pages;
      if (index == null || !(pages >= 3)) return null;
      return { index, page: live.page, pages };
    } catch {
      return null;
    }
  }

  /** The page one turn away (null at either end of the book). */
  #neighbour(dir: Dir): Target | null {
    const here = this.#here();
    if (!here) return null;
    const { index, page, pages } = here;
    if (dir > 0) {
      if (page < pages - 2) return { index, page: page + 1 };
      const next = this.#adjacent(index, 1);
      return next == null ? null : { index: next, page: 1 };
    }
    if (page > 1) return { index, page: page - 1 };
    const prev = this.#adjacent(index, -1);
    return prev == null ? null : { index: prev, page: "last" };
  }

  /**
   * See to it that every section within reach has its ghost, on the page
   * a turn would need, and that no other section has one.
   *
   * Within reach: the sections of the two pages one turn away (first the
   * one in the reading direction), and a neighbouring chapter whose
   * boundary is NEAR_PAGES off or less — its first page ahead, its last
   * page behind. All of it in the background: a turn finds the page
   * there, or (after a jump) waits for it a moment.
   */
  #plan() {
    if (!this.#enabled || this.#host.reducedMotion()) return;
    const here = this.#here();
    if (!here) return;
    for (const ghost of Array.from(this.#ghosts))
      if (ghost.stalled && !this.#engaged(ghost)) this.#drop(ghost);

    const wants = new Map<number, Target>();
    const want = (target: Target | null) => {
      if (!target || wants.has(target.index)) return;
      if (wants.size < MAX_GHOSTS) wants.set(target.index, target);
    };
    const dirs: Dir[] = this.#lastDir > 0 ? [1, -1] : [-1, 1];
    for (const dir of dirs) want(this.#neighbour(dir));
    for (const dir of dirs) {
      const adjacent = this.#adjacent(here.index, dir);
      if (adjacent == null) continue;
      const toEdge = dir > 0 ? here.pages - 2 - here.page : here.page - 1;
      const held = this.#ghosts.some((g) => g.section === adjacent);
      if (toEdge <= (held ? KEEP_PAGES : NEAR_PAGES))
        want({ index: adjacent, page: dir > 0 ? 1 : "last" });
    }

    const free: Ghost[] = [];
    for (const ghost of this.#ghosts) {
      const target = ghost.section == null ? null : wants.get(ghost.section);
      if (target) {
        wants.delete(target.index);
        if (!this.#engaged(ghost)) void ghost.show(target);
      } else if (!this.#engaged(ghost)) free.push(ghost);
    }
    for (const target of wants.values()) {
      const ghost =
        free.pop() ?? (this.#ghosts.length < MAX_GHOSTS ? this.#spawn() : null);
      if (ghost) void ghost.show(target);
    }
    // Well inside a chapter again: the far rendering is given back.
    for (const ghost of free) this.#drop(ghost);
  }

  /** The ghost to show `target` on: the one in that section, else a
   *  free or a new one. Null when only the cover could (it must not
   *  move while it is what the reader sees). */
  #ghostFor(target: Target): Ghost | null {
    let ghost = this.#ghosts.find((g) => g.section === target.index);
    if (ghost?.stalled && !this.#engaged(ghost)) {
      // The step that never reported still has the paginator: a fresh
      // ghost takes the request.
      this.#drop(ghost);
      ghost = undefined;
    }
    if (ghost) return ghost === this.#cover ? null : ghost;
    if (this.#ghosts.length < MAX_GHOSTS) ghost = this.#spawn();
    else {
      const here = this.#here();
      const idle = this.#ghosts.filter((g) => !this.#engaged(g));
      ghost = idle.find((g) => g.section !== here?.index) ?? idle[0];
    }
    // Its section from now on, whenever it is sent there.
    if (ghost) ghost.section = target.index;
    return ghost ?? null;
  }

  /** Ask for `target` and say which ghost has it — at once within the
   *  section a ghost is in, after a load otherwise — or why none does:
   *  the wait is over, the layouts disagree, the ghost stalled, only the
   *  cover could show it. Null once the turn `generation` is abandoned. */
  async #awaitReady(
    target: Target,
    generation: number,
  ): Promise<Ghost | "wait" | "pages" | "stall" | "cover" | null> {
    const deadline = performance.now() + READY_WAIT_MS;
    let misses = 0;
    for (;;) {
      const ghost = this.#ghostFor(target);
      if (!ghost) return "cover";
      const left = deadline - performance.now();
      await Promise.race([ghost.show(target), sleep(left)]);
      if (generation !== this.#generation) return null;
      if (ghost.ready(target)) return ghost;
      if (ghost.stalled) return "stall";
      if (performance.now() >= deadline) return "wait";
      // The step is over without the page: the two layouts disagree on
      // the page count. Right after a relayout that passes within a
      // frame; a disagreement that stays is not worth the whole wait.
      if (!ghost.busy && ++misses >= 3) return "pages";
      await Promise.race([painted(), sleep(left)]);
      if (generation !== this.#generation) return null;
    }
  }

  /** The live paginator reported a page (a turn, a jump, a relayout):
   *  the ghosts follow, once it has stopped reporting. */
  relocated() {
    if (this.#relocating != null) clearTimeout(this.#relocating);
    this.#relocating = setTimeout(() => {
      this.#relocating = null;
      this.#plan();
    }, RELOCATE_SETTLE_MS);
  }

  /** Arrange the ghosts for the page on screen, now. */
  sync() {
    this.#plan();
  }

  // ----------------------------------------------------------- the layers

  #width(): number {
    return this.#host.container.clientWidth || 1;
  }

  /** Where the moving sheet is at progress `p` (0 = the turn has not
   *  begun, 1 = it is complete). Next: the page on screen leaves toward
   *  the side "previous" lies on. Previous: the other comes in from
   *  there. */
  #transform(dir: Dir, p: number): string {
    const side = this.#host.leftward() ? 1 : -1;
    const x = side * (dir > 0 ? p : 1 - p) * this.#width();
    return `translate3d(${x}px, 0, 0)`;
  }

  /** The still page darkens as it is covered, clears as it is bared. */
  #dimOpacity(dir: Dir, p: number): string {
    return String(DIM * (dir > 0 ? 1 - p : p));
  }

  /** The sheet the reader's page is on. */
  #top(): PaginatorElement {
    return this.#cover?.el ?? this.#host.live;
  }

  /** The two sheets of a turn `dir` onto `ghost`'s page, `p` of the way:
   *  the lower page number above, and moving. */
  #arrange(dir: Dir, p: number, ghost: Ghost) {
    const live = this.#host.live;
    const dim = this.#dim;
    const top = this.#top();
    const upper = dir > 0 ? top : ghost.el;
    const lower = dir > 0 ? ghost.el : top;
    for (const other of this.#ghosts) {
      if (other.el === upper || other.el === lower) continue;
      flatten(other.el);
      other.el.style.zIndex = Z_IDLE;
    }
    ghost.el.style.visibility = "";
    flatten(lower);
    if (upper === live) {
      lower.style.zIndex = Z_UNDER;
      dim.style.zIndex = Z_DIM_UNDER;
    } else {
      if (lower !== live) lower.style.zIndex = Z_COVER;
      dim.style.zIndex = Z_DIM_OVER;
      upper.style.zIndex = Z_OVER;
    }
    dim.style.opacity = this.#dimOpacity(dir, p);
    upper.style.transform = this.#transform(dir, p);
    upper.style.boxShadow = SHADOW;
    upper.style.willChange = "transform";
  }

  /** Every sheet flat: the cover (if one is up) over the live page, the
   *  other ghosts under it. */
  #flat() {
    flatten(this.#host.live);
    for (const ghost of this.#ghosts) {
      flatten(ghost.el);
      ghost.el.style.zIndex = ghost === this.#cover ? Z_COVER : Z_IDLE;
    }
    this.#dim.style.opacity = "0";
    this.#dim.style.zIndex = Z_DIM_UNDER;
  }

  #stopCatchUp() {
    this.#joinedAt = 0;
    if (this.#frame) cancelAnimationFrame(this.#frame);
    this.#frame = 0;
  }

  /** No sheet is the finger's (any more). */
  #letGo() {
    this.#dragDir = 0;
    this.#progress = 0;
    this.#partner = null;
    this.#joining = null;
    this.#lateAt = 0;
    this.#stopCatchUp();
  }

  async #animate(dir: Dir, from: number, to: number, ms: number, ghost: Ghost) {
    const mover = dir > 0 ? this.#top() : ghost.el;
    if (typeof mover.animate !== "function") return;
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
   *  started). A turn made leaves `ghost` as the cover and the live
   *  paginator owing it. */
  async #run(dir: Dir, from: number, to: 0 | 1, ms: number, ghost: Ghost) {
    const generation = this.#generation;
    this.#state = "settle";
    this.#partner = ghost;
    this.#stopCatchUp();
    // A touch during the slide belongs to the reader's container, not to
    // a page that is on its way out: taps and swipes are heard there.
    this.#host.live.style.pointerEvents = "none";
    this.#note({ at: this.#now(), dir, how: to ? "slide" : "spring" });
    // The end state stands in the styles; the animation plays over it.
    this.#arrange(dir, to, ghost);
    if (from !== to) await this.#animate(dir, from, to, ms, ghost);
    if (generation !== this.#generation) return;
    this.#state = "idle";
    this.#letGo();
    if (to === 1) {
      // The ghost covers the live paginator while that makes the same
      // turn underneath: nothing changes on screen.
      this.#lastDir = dir;
      this.#cover = ghost;
      this.#owed += dir;
    }
    this.#flat();
    this.#settled();
  }

  /**
   * Have the live paginator make the turns it is owed. Within the
   * section it is in that is a scroll, made at once. Into another
   * section it is a load that keeps the page's thread — the one the
   * next turn has to be heard and started on — for as long as the
   * chapter takes to lay out: that waits until the reader has stayed on
   * the page a moment, unless a turn cannot be played without it
   * (`urgent`).
   */
  #catchUp(urgent: boolean) {
    if (!this.#cover || this.#chasing) return;
    if (this.#dwell != null) clearTimeout(this.#dwell);
    this.#dwell = null;
    if (this.#owed === 0) return;
    if (urgent || !this.#far()) {
      void this.#chase();
      return;
    }
    this.#dwell = setTimeout(() => {
      this.#dwell = null;
      // (Mid-turn: asked for again when that turn has settled.)
      if (this.#state === "idle" && !this.#finger) void this.#chase();
    }, DWELL_MS);
  }

  /** The page under the cover is in another section than the live
   *  paginator is. (At either end of the book the reader's "next" and
   *  "previous" are read off the live page: no putting off there.) */
  #far(): boolean {
    const { live } = this.#host;
    try {
      if (live.atStart || live.atEnd) return false;
      return live.getContents()[0]?.index !== this.#cover?.index;
    } catch {
      return false;
    }
  }

  /**
   * The live paginator makes the turns it is owed, one after another,
   * under the cover. By the time a load is done the reader may have
   * turned again — or back, in which case nothing more is owed.
   */
  async #chase() {
    if (this.#chasing) return;
    this.#chasing = true;
    const generation = this.#generation;
    const live = this.#host.live;
    for (;;) {
      const doc = live.getContents()[0]?.doc;
      while (this.#owed !== 0) {
        const dir: Dir = this.#owed > 0 ? 1 : -1;
        this.#owed -= dir;
        try {
          await this.#host.turnLive(dir);
        } catch (e) {
          console.warn(e);
        }
        if (generation !== this.#generation) return;
      }
      // A turn into another section put a new document under the cover:
      // its fonts and the pictures on its page first.
      const landed = live.getContents()[0]?.doc;
      if (landed && landed !== doc) await this.#drawn(landed);
      if (generation !== this.#generation) return;
      // Under the cover until its new page has been painted.
      await painted();
      if (generation !== this.#generation) return;
      if (this.#owed === 0) break;
    }
    this.#chasing = false;
    if (!this.#uncover()) return;
    if (this.#state === "idle") this.#afterTurn();
    // A finger waiting for a page only the cover had.
    else if (this.#state === "drag") this.#follow(false);
  }

  /** A freshly loaded live document has what its page needs to look as
   *  the cover does: its fonts in, the pictures on the page decoded.
   *  Bounded — a slow font must not keep the reader behind the cover. */
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

  /** Take the cover away once the live page beneath it is the same page
   *  — unless it is one of two sheets in motion. Returns whether the
   *  live page is (now) the one on top. */
  #uncover(): boolean {
    if (!this.#cover) return true;
    if (this.#chasing || this.#owed !== 0) return false;
    if (this.#state === "settle" || (this.#state === "drag" && this.#dragDir))
      return false;
    this.#cover = null;
    if (this.#dwell != null) clearTimeout(this.#dwell);
    this.#dwell = null;
    this.#flat();
    this.#host.live.style.pointerEvents = "";
    return true;
  }

  /** Back at rest after a turn, a spring back or a drag that came to
   *  nothing. */
  #settled() {
    if (this.#uncover()) this.#host.live.style.pointerEvents = "";
    else this.#catchUp(false);
    this.#afterTurn();
  }

  #afterTurn() {
    if (this.#finger) {
      // A finger came down while the turn was finishing: it has the
      // sheets from here, and the one it pulls at joins it where it is.
      this.#pending = null;
      this.#state = "drag";
      this.#follow(false);
      return;
    }
    const pending = this.#pending;
    this.#pending = null;
    if (pending) this.#host.request(pending);
    else this.#plan();
  }

  /** Abandon whatever is in progress: every sheet flat, the live one on
   *  top. For navigation, which is not a page turn. */
  cancel() {
    this.#generation++;
    this.#pending = null;
    this.#finger = false;
    const animations = this.#animations;
    this.#animations = [];
    for (const a of animations) a.cancel();
    this.#cover = null;
    this.#owed = 0;
    this.#chasing = false;
    if (this.#dwell != null) clearTimeout(this.#dwell);
    this.#dwell = null;
    this.#state = "idle";
    this.#letGo();
    this.#flat();
    this.#host.live.style.pointerEvents = "";
  }

  // ---------------------------------------------------------------- turns

  /** Keep `dir` for when it can be played. One at most waits — quick
   *  paging never builds a backlog — and a turn back takes the waiting
   *  turn forward away again rather than replace it. */
  #queue(dir: Dir) {
    this.#pending = this.#pending === -dir ? null : dir;
  }

  /**
   * A page turn without the finger (tap zone, key, wheel, toolbar).
   * Returns false when there is nothing to slide to; a turn taken here
   * that no ghost then manages to show goes back through `fallback`.
   *
   * A turn asked for while another is still sliding ends that slide at
   * once and follows it.
   */
  turn(dir: Dir): boolean {
    if (!this.#enabled) return false;
    switch (this.#state) {
      case "drag":
        return true; // a finger is on the page
      case "settle":
        this.#queue(dir);
        this.#finishAnimations();
        return true;
      case "prepare":
        this.#queue(dir);
        return true;
    }
    // A turn is already waiting for the live page under the cover.
    if (this.#pending) {
      this.#queue(dir);
      return true;
    }
    const target = this.#neighbour(dir);
    if (!target) return !!this.#cover;
    this.#begin(dir, target);
    return true;
  }

  /** Play the turn to `target` from rest, as soon as a ghost has the
   *  page: at once when one is on it, after a short wait when it has to
   *  be fetched. A page that does not come hands the turn back. */
  #begin(dir: Dir, target: Target) {
    // Whatever becomes of this turn, the reader is going this way: the
    // ghosts are arranged for that afterwards.
    this.#lastDir = dir;
    const generation = this.#generation;
    this.#state = "prepare";
    void this.#awaitReady(target, generation).then((result) => {
      if (generation !== this.#generation || this.#state !== "prepare") return;
      if (result && typeof result === "object") {
        void this.#run(dir, 0, 1, TURN_MS, result);
        return;
      }
      this.#state = "idle";
      const queued = this.#pending;
      this.#pending = null;
      if (this.#cover || result === "cover") {
        // The page is the cover's own to show, or still on its way: the
        // turn is played once the live page has caught up. (Nothing
        // fades under a cover.)
        if (queued !== -dir) this.#pending = dir;
        if (this.#uncover()) this.#afterTurn();
        else this.#catchUp(true);
        return;
      }
      this.#note({
        at: this.#now(),
        dir,
        how: "fade",
        why: result === "pages" || result === "stall" ? result : "wait",
      });
      this.#host.fallback(dir);
      if (queued) this.#host.request(queued);
    });
  }

  /**
   * The finger moved by (previous − current) px along the screen's x
   * axis. Returns whether the slide has the gesture. Toward the end of
   * the book nothing moves; toward a page no ghost has yet nothing moves
   * until one has, and then the sheet joins the finger where it is by
   * now. While a turn is still finishing (`blocked`: or a fallback fade
   * is running) the finger is only followed in the books: the slide
   * under way is cut short, and the sheet joins once it is over.
   */
  dragBy(dx: number, blocked = false): boolean {
    if (!this.#enabled || this.#host.reducedMotion()) return false;
    if (!this.#finger) {
      this.#finger = true;
      this.#x = 0;
    }
    this.#x -= dx;
    this.#movedAt = performance.now();
    if (blocked) return true;
    if (this.#state === "idle") {
      this.#state = "drag";
      this.#letGo();
    }
    if (this.#state === "drag") this.#follow(false);
    else if (this.#state === "settle") this.#finishAnimations();
    return true;
  }

  /** The way the finger has pulled so far. */
  #pull(): Dir | 0 {
    const p = (this.#host.leftward() ? 1 : -1) * this.#x;
    return p > 0 ? 1 : p < 0 ? -1 : 0;
  }

  /** Put the sheet where the finger is — or, while no ghost has the
   *  page it is pulling toward, send for it. `joining`: a ghost has just
   *  finished a step this drag was waiting on. */
  #follow(joining: boolean) {
    const dir = this.#pull();
    const target = dir ? this.#neighbour(dir) : null;
    const ghost = target ? this.#ghostFor(target) : null;
    if (!dir || !target || !ghost || !ghost.ready(target)) {
      if (this.#dragDir) this.#flat();
      this.#dragDir = 0;
      this.#progress = 0;
      this.#partner = null;
      this.#lateAt = 0;
      this.#stopCatchUp();
      if (!dir || !target) return;
      this.#lastDir = dir;
      // A page only the cover could show comes with the live page.
      if (!ghost) {
        this.#catchUp(true);
        return;
      }
      // (A step that ended without the page — the two layouts disagree —
      // is not asked for again until the finger moves.)
      if (joining) return;
      const step = ghost.show(target);
      if (this.#joining === step) return;
      this.#joining = step;
      void step.then(() => {
        if (this.#joining !== step) return;
        this.#joining = null;
        if (this.#state === "drag" && !this.#dragDir) this.#follow(true);
      });
      return;
    }
    if (this.#dragDir !== dir || this.#partner !== ghost) {
      this.#dragDir = dir;
      this.#partner = ghost;
      this.#joining = null;
      // The sheet appears under a finger that is already some way off:
      // it runs up to it rather than jump.
      this.#stopCatchUp();
      this.#lateAt = 0;
      if (Math.abs(this.#x) > CATCH_UP_MIN_PX)
        this.#joinedAt = this.#lateAt = performance.now();
    }
    this.#paint();
  }

  #paint() {
    const dir = this.#dragDir;
    const ghost = this.#partner;
    if (!dir || !ghost) return;
    let p = Math.min(1, Math.abs(this.#x) / this.#width());
    if (this.#joinedAt) {
      const t = (performance.now() - this.#joinedAt) / CATCH_UP_MS;
      if (t >= 1) this.#joinedAt = 0;
      // Ease-out toward wherever the finger is by now.
      else p *= 1 - (1 - t) ** 3;
    }
    this.#progress = p;
    this.#arrange(dir, p, ghost);
    if (this.#joinedAt && !this.#frame)
      this.#frame = requestAnimationFrame(() => {
        this.#frame = 0;
        if (this.#state === "drag") this.#paint();
      });
  }

  /** The finger's velocity toward completing the turn `dir` (0 when it
   *  had come to rest before lifting). */
  #toward(dir: Dir, vx: number): number {
    const side = this.#host.leftward() ? 1 : -1;
    const stale = performance.now() - this.#movedAt > VELOCITY_STALE_MS;
    return stale || !Number.isFinite(vx) ? 0 : side * -vx * dir;
  }

  /** Whether a release `p` of the way across, moving at `vx`, makes the
   *  turn `dir` — for a sheet the finger had. */
  #completes(dir: Dir, p: number, vx: number): boolean {
    const toward = this.#toward(dir, vx);
    return toward > FLICK || (p > 0.5 && toward > -FLICK);
  }

  /** The same for a swipe no sheet followed: to the reader it was a
   *  plain swipe, and turns the page as one does. */
  #swiped(dir: Dir, vx: number): boolean {
    const toward = this.#toward(dir, vx);
    return toward > FLICK || (Math.abs(this.#x) > SWIPE_PX && toward > -FLICK);
  }

  /**
   * The finger lifted, moving at `vx` px/ms (previous − current). With a
   * sheet under it, how far that has come and how fast it was going
   * decide between making the turn and springing back. A swipe that
   * moved nothing — its page was not there yet, or the turn before it
   * was still finishing — is judged as the plain swipe it looked like,
   * and its turn played as soon as it can be.
   *
   * Returns false when the slide leaves the gesture to the caller: there
   * was no page to pull toward (the end of the book), or a fallback fade
   * has the page — a plain threshold swipe either way.
   */
  dragEnd(vx: number): boolean {
    if (!this.#finger) return false;
    this.#finger = false;
    const pulled = this.#pull();
    if (this.#state !== "drag") {
      if (this.#state === "idle") return false;
      // A turn is finishing: this one follows it.
      if (pulled && this.#swiped(pulled, vx)) this.#queue(pulled);
      return true;
    }
    const p = Math.min(1, Math.abs(this.#x / this.#width()));
    const dir = this.#dragDir;
    const ghost = this.#partner;
    if (!dir || !ghost) {
      const target = pulled ? this.#neighbour(pulled) : null;
      const complete = !!pulled && this.#swiped(pulled, vx);
      this.#state = "idle";
      this.#letGo();
      if (!pulled || !target) {
        this.#settled();
        return false;
      }
      if (complete) this.#begin(pulled, target);
      else this.#settled();
      return true;
    }
    // A sheet that had only just reached the finger was not seen moving.
    const unseen =
      this.#lateAt !== 0 && performance.now() - this.#lateAt < SEEN_MS;
    const complete = unseen
      ? this.#swiped(dir, vx)
      : this.#completes(dir, p, vx);
    // From where the sheet stands, which is short of the finger while it
    // is still catching up.
    const from = this.#progress;
    const left = complete ? 1 - from : from;
    const ms = Math.max(SETTLE_MIN_MS, Math.round(TURN_MS * left));
    void this.#run(dir, from, complete ? 1 : 0, ms, ghost);
    return true;
  }

  /** The touch ended without a release (cancelled, or a new one began):
   *  a sheet left displaced springs back. */
  dragCancel() {
    this.#finger = false;
    if (this.#state !== "drag") return;
    const dir = this.#dragDir;
    const ghost = this.#partner;
    if (!dir || !ghost) {
      this.#state = "idle";
      this.#letGo();
      this.#settled();
      return;
    }
    void this.#run(dir, this.#progress, 0, SETTLE_MIN_MS, ghost);
  }
}
