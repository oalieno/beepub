/**
 * Image prefetch for the sections around the one on screen.
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
 * It never touches the parser's own blob-URL refcounts (loading a section
 * through the parser ahead of time would, and the parser's accounting for
 * out-of-band loads is not balanced). Memory is bounded by the window:
 * every pass drops whatever it no longer names — including the bytes the
 * parser itself pulled through the cache for sections now out of range.
 */
import type { BookLoader } from "./loaders";

/** Sections ahead / behind the current one to warm. */
const FORWARD = 3;
const BACKWARD = 1;

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

  constructor(inner: BookLoader) {
    this.#inner = inner;
    // Every read goes through the cache, the parser's own included: what
    // the paginator fetched for the section on screen is still in memory
    // when the reader steps back into it, until it leaves the window.
    this.loader = {
      loadText: (href) => this.#text(href),
      loadBlob: (href) => this.#blob(href),
      getSize: (href) => inner.getSize(href),
    };
  }

  /** The spine, once the book is parsed. */
  open(sections: PrefetchSection[]) {
    this.#sections = sections;
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
    void this.#warm(window, generation);
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
      p.catch(() => this.#texts.delete(href));
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
    for (const href of Array.from(this.#texts.keys()))
      if (!keep.has(href)) this.#texts.delete(href);
    for (const id of Array.from(this.#images.keys()))
      if (!keep.has(id)) this.#images.delete(id);
  }

  destroy() {
    this.#generation++;
    this.#blobs.clear();
    this.#texts.clear();
    this.#images.clear();
    this.#sections = [];
  }
}
