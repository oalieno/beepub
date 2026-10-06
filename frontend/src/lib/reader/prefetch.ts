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
  /** One more section's document can be had without the network. */
  onavailable: (() => void) | null = null;

  constructor(inner: BookLoader) {
    this.#inner = inner;
    // Every read goes through the cache, the parser's own included: what
    // the paginator fetched for the section on screen is still in memory
    // when the reader steps back into it, until it leaves the window.
    this.loader = {
      loadText: (href) => this.#text(href),
      loadBlob: (href) =>
        this.#blob(href).catch((e) => {
          console.warn(`[reader] could not load ${href}`, e);
          return new Blob([]);
        }),
      getSize: (href) => inner.getSize(href),
    };
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

  /** The section on screen changed: warm its neighbours, drop the rest.
   *  A newer call supersedes an unfinished pass. */
  around(index: number) {
    const generation = ++this.#generation;
    const sections = this.#sections;
    if (sections.length === 0) return;
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
    void this.#chapters(index, generation).then(() =>
      this.#warm(window, generation),
    );
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
          if (this.#spine.has(href)) this.onavailable?.();
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
    this.#blobs.clear();
    this.#texts.clear();
    this.#have.clear();
    this.#spine.clear();
    this.onavailable = null;
    this.#images.clear();
    this.#sections = [];
  }
}
