/**
 * Object URLs for page images, fetched through the book loader (server
 * streamer or the local zip alike) and kept in a small LRU so turning back
 * a page is free and a whole comic never sits in memory at once.
 */
import type { BookLoader } from "./loaders/types";

export class PageImageCache {
  #loader: BookLoader;
  #capacity: number;
  #urls = new Map<string, string>();
  #pending = new Map<string, Promise<string>>();
  #destroyed = false;

  constructor(loader: BookLoader, capacity = 16) {
    this.#loader = loader;
    this.#capacity = capacity;
  }

  /** The object URL for `path`, loading it on first use. Rejects when the
   *  entry is missing or empty so the caller can show a broken page. */
  get(path: string): Promise<string> {
    const hit = this.#urls.get(path);
    if (hit) {
      // Refresh recency.
      this.#urls.delete(path);
      this.#urls.set(path, hit);
      return Promise.resolve(hit);
    }
    const inflight = this.#pending.get(path);
    if (inflight) return inflight;
    const promise = this.#load(path);
    this.#pending.set(path, promise);
    return promise;
  }

  async #load(path: string): Promise<string> {
    try {
      const blob = await this.#loader.loadBlob(path);
      if (this.#destroyed) throw new Error("cache destroyed");
      if (blob.size === 0) throw new Error(`empty page image: ${path}`);
      const url = URL.createObjectURL(blob);
      this.#urls.set(path, url);
      this.#evict();
      return url;
    } finally {
      this.#pending.delete(path);
    }
  }

  /** Warm the cache for the pages about to be shown. Failures are the
   *  page's problem when it is actually displayed. */
  prefetch(paths: readonly (string | null)[]) {
    for (const path of paths) {
      if (path && !this.#urls.has(path) && !this.#pending.has(path))
        void this.get(path).catch(() => {});
    }
  }

  #evict() {
    while (this.#urls.size > this.#capacity) {
      const oldest = this.#urls.keys().next().value;
      if (oldest === undefined) break;
      const url = this.#urls.get(oldest);
      this.#urls.delete(oldest);
      if (url) URL.revokeObjectURL(url);
    }
  }

  destroy() {
    this.#destroyed = true;
    for (const url of this.#urls.values()) URL.revokeObjectURL(url);
    this.#urls.clear();
  }
}
