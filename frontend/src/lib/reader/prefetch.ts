/**
 * Prefetch for the sections around the one on screen: their text, and
 * their images.
 *
 * The paginator loads a section by asking the parser for its blob URL,
 * and the parser only answers once every image the section references
 * has been fetched and minted — so the first turn into a chapter that
 * opens on a plate waits for the plate (the Bearer + blob path on the
 * app makes that wait visible). This wraps the BookLoader with a small
 * memory cache and fills it ahead: the sections after (and the one
 * before) the current one have their markup scanned for `<img>` and SVG
 * `<image>` sources and those bytes fetched now, so the parser's later
 * `loadBlob` is answered from memory.
 *
 * Text comes first and reaches further. The window above counts spine
 * items, and in a light novel a run of illustration plates and title
 * pages can fill it without a line of prose: every pass therefore walks
 * on, each way, until it has the markup of a section that is a chapter of
 * text (TEXT_REACH items at most), so reading on into the next chapter —
 * or back into the one before — finds its document in memory. A book's
 * stylesheets are text too and come with the first section that links
 * them; fonts are fetched by the parser with those sheets and stay with
 * it while a section that uses them is loaded.
 *
 * Text is kept for the session: a chapter is a few tens of kilobytes,
 * and one already fetched must not need the network again (a reader who
 * loses the connection can still go back). Images are bounded by the
 * window: every pass drops the ones it no longer names — including the
 * bytes the parser itself pulled through the cache for sections now out
 * of range. Which sections can be shown without the network is therefore
 * known here (`available`), and `onavailable` says when one more can.
 *
 * Behind all of that, and only for a book that is streamed, the rest of
 * the book's text is brought in slowly (the crawl), so that a reader who
 * loses the connection in the middle of a book can read on. It is text
 * alone — the spine's documents, never an image or a font — and it lives
 * and dies with the session like any other text here. It goes forward
 * from the section on screen to the end of the spine, one request at a
 * time with a pause before each, and only while nothing else is being
 * asked for: a pass for the current position, or a read of the parser's
 * (a page turn, a jump, a search), sends it to wait, and it goes on from
 * where the reader then is — what is already held costs nothing, so a
 * move never starts it over, and it has no part in the passes' generation
 * count. It rests once CRAWL_AHEAD_BYTES of text lie ahead of the reader
 * and sets off again when reading has brought that under CRAWL_LOW_BYTES,
 * so a serial of millions of characters is not pulled whole on opening.
 * It keeps still while the document is hidden, while the connection is
 * one to be sparing with (`backgroundFetchAllowed`), and after a request
 * that failed — until the reader next moves or the connection is back.
 *
 * It never touches the parser's own blob-URL refcounts (loading a section
 * through the parser ahead of time would, and the parser's accounting for
 * out-of-band loads is not balanced).
 *
 * The loader handed to the parser also decides what a failed request
 * costs. An image or a font that cannot be fetched is answered with
 * nothing, so its section still loads (and the fetch is tried again the
 * next time the section is); a section's own document, or a stylesheet —
 * which decides the writing mode and with it every page — fails the load.
 */
import {
  backgroundFetchAllowed,
  getIsOnline,
  isOnline,
} from "$lib/services/network";

import type { BookLoader } from "./loaders";

/** Sections ahead / behind the current one to warm. */
const FORWARD = 3;
const BACKWARD = 1;
/** How many spine items a pass looks through, each way, for a chapter of
 *  text. */
const TEXT_REACH = 12;
/** Characters of text that make a section a chapter rather than a plate,
 *  a title page or a divider. */
const TEXT_MIN = 400;
/** Bytes of text ahead of the reader at which the crawl rests. */
const CRAWL_AHEAD_BYTES = 3 * 1024 * 1024;
/** Bytes of text ahead of the reader under which a resting crawl sets
 *  off again. */
const CRAWL_LOW_BYTES = 1024 * 1024;
/** The pause before each of the crawl's requests. */
const CRAWL_PAUSE_MS = 250;

/** What the crawl is doing: on its way to a request (`waiting`), out on
 *  one (`fetching`), standing aside for a pass or a read (`yielding`),
 *  resting on enough text (`full`), at the end of the spine (`done`),
 *  kept from the network by the document being hidden (`hidden`), by
 *  the kind of connection (`withheld`), by there being none (`offline`)
 *  or by a request that failed (`failed`), or not to run at all
 *  (`off`). */
export type CrawlState =
  | "waiting"
  | "fetching"
  | "yielding"
  | "full"
  | "done"
  | "hidden"
  | "withheld"
  | "offline"
  | "failed"
  | "off";

const encoder = new TextEncoder();

/** Roughly how much text a section's markup holds. */
function textLength(markup: string): number {
  const body = markup.replace(/^[\s\S]*?<body\b[^>]*>/i, "");
  return body.replace(/<[^>]*>/g, "").replace(/\s+/g, "").length;
}

interface PrefetchSection {
  id: string;
  linear?: string;
}

/** `src`/`href` of the images a section references, resolved against the
 *  section's own path. Regex over the markup: the parser's document is
 *  not built yet at this point and a DOMParser pass per section would
 *  cost more than the fetches it saves. */
export function imageHrefs(markup: string, sectionHref: string): string[] {
  const out = new Set<string>();
  const base = new URL(sectionHref, "epub:/");
  const add = (raw: string | undefined) => {
    if (!raw) return;
    const value = raw.trim();
    if (!value || /^(data|blob|https?):/i.test(value) || value.startsWith("#"))
      return;
    try {
      const url = new URL(value, base);
      if (url.protocol !== "epub:") return;
      // Back to the manifest's shape: decoded, no leading slash.
      out.add(decodeURIComponent(url.pathname.replace(/^\//, "")));
    } catch {
      // unparsable href — the section itself will complain
    }
  };
  for (const m of markup.matchAll(/<img\b[^>]*?\ssrc\s*=\s*["']([^"']*)["']/gi))
    add(m[1]);
  for (const m of markup.matchAll(
    /<image\b[^>]*?\s(?:xlink:)?href\s*=\s*["']([^"']*)["']/gi,
  ))
    add(m[1]);
  return Array.from(out);
}

export class ImagePrefetcher {
  readonly loader: BookLoader;
  #inner: BookLoader;
  #blobs = new Map<string, Promise<Blob>>();
  #texts = new Map<string, Promise<string | null>>();
  /** Section id → image hrefs, once scanned. */
  #images = new Map<string, string[]>();
  #generation = 0;
  #sections: PrefetchSection[] = [];
  /** Hrefs whose text is in memory. */
  #have = new Set<string>();
  #spine = new Set<string>();
  /** Section id → bytes of its document, once in memory. */
  #sizes = new Map<string, number>();
  /** Sections the book names and does not have. */
  #absent = new Set<string>();
  /** The section on screen, as around() last heard. */
  #index = -1;
  /** Passes not finished, and reads of the parser's not answered: the
   *  crawl waits for both. */
  #passes = 0;
  #reads = 0;
  #crawls: boolean;
  #crawling = false;
  #state: CrawlState;
  /** The section the crawl is out for. */
  #fetching: string | null = null;
  #resting = false;
  #failed = false;
  #dead = false;
  /** Ends the crawl's pause early (destroy). */
  #wake: (() => void) | null = null;
  #unlisten: (() => void) | null = null;
  /** One more section's document can be had without the network. */
  onavailable: (() => void) | null = null;

  /** @param crawl  Whether the rest of the book's text is brought in
   *    behind the reader's back: for a streamed book, not for one that is
   *    on the device whole. */
  constructor(inner: BookLoader, { crawl = true }: { crawl?: boolean } = {}) {
    this.#inner = inner;
    this.#crawls = crawl;
    this.#state = crawl ? "waiting" : "off";
    // Every read goes through the cache, the parser's own included: what
    // the paginator fetched for the section on screen is still in memory
    // when the reader steps back into it, until it leaves the window.
    this.loader = {
      loadText: (href) => this.#read(this.#text(href)),
      loadBlob: (href) =>
        this.#read(this.#blob(href)).catch((e) => {
          console.warn(`[reader] could not load ${href}`, e);
          return new Blob([]);
        }),
      getSize: (href) => inner.getSize(href),
    };
    if (crawl) this.#listen();
  }

  /** What would let a waiting crawl go on: the document shown again, the
   *  connection back. */
  #listen() {
    const shown = () => {
      if (document.visibilityState === "visible") void this.#go();
    };
    const back = () => {
      this.#failed = false;
      void this.#go();
    };
    document.addEventListener("visibilitychange", shown);
    window.addEventListener("online", back);
    // (The app's own word on the server; it is told at once, and then on
    // every change.)
    const unsubscribe = isOnline.subscribe((online) => {
      if (online) back();
    });
    this.#unlisten = () => {
      document.removeEventListener("visibilitychange", shown);
      window.removeEventListener("online", back);
      unsubscribe();
    };
  }

  /** A read made for the page: the crawl stands aside until it is
   *  answered. */
  #read<T>(p: Promise<T>): Promise<T> {
    this.#reads++;
    const over = () => {
      this.#reads--;
      void this.#go();
    };
    p.then(over, over);
    return p;
  }

  /** The spine, once the book is parsed. */
  open(sections: PrefetchSection[]) {
    this.#sections = sections;
    this.#spine = new Set(sections.map((s) => s.id));
  }

  /** Whether the section's document is in memory: it can be shown
   *  without the network. */
  available(id: string): boolean {
    return this.#have.has(id);
  }

  /** Where the crawl stands (a debug handle: nothing acts on it). */
  get crawl(): { state: CrawlState; ahead: number; fetching: string | null } {
    return {
      state: this.#state,
      ahead: this.#ahead().bytes,
      fetching: this.#fetching,
    };
  }

  /** The section on screen changed: warm its neighbours, drop the rest.
   *  A newer call supersedes an unfinished pass. */
  around(index: number) {
    const generation = ++this.#generation;
    const sections = this.#sections;
    if (sections.length === 0) return;
    this.#index = index;
    // The reader moved: a request that failed may be made again.
    this.#failed = false;
    this.#passes++;
    if (this.#crawls && !this.#fetching) this.#state = "yielding";
    const window: PrefetchSection[] = [];
    const current = sections[index];
    if (current) window.push(current);
    let ahead = 0;
    for (let i = index + 1; i < sections.length && ahead < FORWARD; i++) {
      if (sections[i].linear === "no") continue;
      window.push(sections[i]);
      ahead++;
    }
    let behind = 0;
    for (let i = index - 1; i >= 0 && behind < BACKWARD; i--) {
      if (sections[i].linear === "no") continue;
      window.push(sections[i]);
      behind++;
    }
    const over = () => {
      this.#passes--;
      void this.#go();
    };
    void this.#chapters(index, generation)
      .then(() => this.#warm(window, generation))
      .then(over, over);
  }

  /** The text held ahead of the reader, as far as it is unbroken, and the
   *  first section after it that is not held. */
  #ahead(): { bytes: number; next: string | null } {
    const sections = this.#sections;
    let bytes = 0;
    for (let i = this.#index + 1; i > 0 && i < sections.length; i++) {
      const { id, linear } = sections[i];
      if (linear === "no" || this.#absent.has(id)) continue;
      if (!this.#have.has(id)) return { bytes, next: id };
      bytes += this.#sizes.get(id) ?? 0;
    }
    return { bytes, next: null };
  }

  /** Whether the crawl has to keep off the network just now, and says
   *  why. Each of these ends with a call to #go. */
  #held(): boolean {
    if (this.#passes > 0 || this.#reads > 0) this.#state = "yielding";
    else if (document.visibilityState !== "visible") this.#state = "hidden";
    else if (this.#failed) this.#state = "failed";
    else if (navigator.onLine === false || !getIsOnline())
      this.#state = "offline";
    else return false;
    return true;
  }

  /** The crawl: the text of the sections ahead, one at a time, for as
   *  long as nothing stands in its way. One loop at most; a call while it
   *  runs is nothing, and one after it stopped takes it up where the
   *  reader now is. */
  async #go() {
    if (!this.#crawls || this.#crawling || this.#dead || this.#index < 0)
      return;
    this.#crawling = true;
    try {
      for (;;) {
        if (this.#held()) return;
        this.#state = "waiting";
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, CRAWL_PAUSE_MS);
          this.#wake = () => {
            clearTimeout(timer);
            resolve();
          };
        });
        this.#wake = null;
        if (this.#dead || this.#held()) return;
        if (!backgroundFetchAllowed()) {
          this.#state = "withheld";
          return;
        }
        const { bytes, next } = this.#ahead();
        if (!next) {
          this.#state = "done";
          return;
        }
        if (bytes >= CRAWL_AHEAD_BYTES) this.#resting = true;
        else if (bytes < CRAWL_LOW_BYTES) this.#resting = false;
        if (this.#resting) {
          this.#state = "full";
          return;
        }
        this.#state = "fetching";
        this.#fetching = next;
        try {
          if ((await this.#text(next)) == null) this.#absent.add(next);
        } catch {
          // offline, or the server is not answering: not asked again
          // until the reader moves or the connection is back
          this.#failed = true;
        } finally {
          this.#fetching = null;
        }
        if (this.#dead) return;
      }
    } finally {
      this.#crawling = false;
    }
  }

  /** The markup of the sections on the way to the next chapter of text,
   *  ahead and then behind. */
  async #chapters(index: number, generation: number) {
    const sections = this.#sections;
    for (const dir of [1, -1]) {
      let seen = 0;
      for (
        let i = index + dir;
        i >= 0 && i < sections.length && seen < TEXT_REACH;
        i += dir
      ) {
        if (sections[i].linear === "no") continue;
        seen++;
        let markup: string | null = null;
        try {
          markup = await this.#text(sections[i].id);
        } catch {
          // offline, or the request failed: the turn itself asks again
          break;
        }
        if (generation !== this.#generation) return;
        if (markup && textLength(markup) >= TEXT_MIN) break;
      }
    }
  }

  async #warm(window: PrefetchSection[], generation: number) {
    // The current section is retained (its images may be re-read by a
    // reflow) but never scanned: the parser is loading it right now.
    const [current, ...neighbours] = window;
    const keep = new Set<string>();
    if (current) {
      keep.add(current.id);
      for (const href of this.#images.get(current.id) ?? []) keep.add(href);
    }
    for (const section of neighbours) {
      if (generation !== this.#generation) return;
      keep.add(section.id);
      let images = this.#images.get(section.id);
      if (!images) {
        const text = this.#text(section.id);
        let markup: string | null = null;
        try {
          markup = await text;
        } catch {
          markup = null;
        }
        if (generation !== this.#generation) return;
        images = markup ? imageHrefs(markup, section.id) : [];
        this.#images.set(section.id, images);
      }
      for (const href of images) {
        keep.add(href);
        this.#blob(href);
      }
      // One section at a time keeps the page's own fetches ahead of ours.
      await Promise.allSettled(images.map((href) => this.#blobs.get(href)));
    }
    if (generation !== this.#generation) return;
    this.#retain(keep);
  }

  #text(href: string): Promise<string | null> {
    let p = this.#texts.get(href);
    if (!p) {
      p = this.#inner.loadText(href);
      this.#texts.set(href, p);
      // A failed fetch must not be served to the parser later: drop it so
      // the real load retries.
      p.then(
        (text) => {
          if (text == null || this.#texts.get(href) !== p) return;
          this.#have.add(href);
          if (!this.#spine.has(href)) return;
          this.#sizes.set(href, encoder.encode(text).length);
          this.onavailable?.();
        },
        () => {
          if (this.#texts.get(href) === p) this.#texts.delete(href);
        },
      );
    }
    return p;
  }

  #blob(href: string): Promise<Blob> {
    let p = this.#blobs.get(href);
    if (!p) {
      p = this.#inner.loadBlob(href);
      this.#blobs.set(href, p);
      p.catch(() => this.#blobs.delete(href));
    }
    return p;
  }

  #retain(keep: Set<string>) {
    for (const href of Array.from(this.#blobs.keys()))
      if (!keep.has(href)) this.#blobs.delete(href);
    for (const id of Array.from(this.#images.keys()))
      if (!keep.has(id)) this.#images.delete(id);
  }

  destroy() {
    this.#generation++;
    this.#dead = true;
    this.#state = "off";
    this.#wake?.();
    this.#wake = null;
    this.#unlisten?.();
    this.#unlisten = null;
    this.#sizes.clear();
    this.#absent.clear();
    this.#blobs.clear();
    this.#texts.clear();
    this.#have.clear();
    this.#spine.clear();
    this.onavailable = null;
    this.#images.clear();
    this.#sections = [];
  }
}
