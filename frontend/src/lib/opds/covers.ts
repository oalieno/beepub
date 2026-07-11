/**
 * Thumbnail loader for credentialed catalogs — a plain <img> can't send
 * Basic auth, so covers are fetched through the OPDS transport as data
 * URIs. Bounded concurrency keeps a 50-entry page from stampeding the
 * server; the cache lives as long as the loader (one per feed-page
 * session). Uncredentialed catalogs never need this: their covers load
 * as ordinary <img> subresources.
 */
import { fetchImageDataUri, type OpdsCredentials } from "./client";

const CONCURRENCY = 4;

export class OpdsCoverLoader {
  private cache = new Map<string, string | null>();
  private pending = new Map<string, Promise<string | null>>();
  private waiters: Array<() => void> = [];
  private active = 0;

  constructor(private readonly creds: OpdsCredentials) {}

  /** Data URI for the cover, or null when it can't be fetched. */
  load(url: string): Promise<string | null> {
    const cached = this.cache.get(url);
    if (cached !== undefined) return Promise.resolve(cached);
    const pending = this.pending.get(url);
    if (pending) return pending;
    const run = this.acquire()
      .then(() => fetchImageDataUri(url, this.creds))
      .then((uri) => {
        this.cache.set(url, uri);
        return uri;
      })
      .finally(() => {
        this.pending.delete(url);
        this.release();
      });
    this.pending.set(url, run);
    return run;
  }

  private acquire(): Promise<void> {
    if (this.active < CONCURRENCY) {
      this.active++;
      return Promise.resolve();
    }
    return new Promise((resolve) => this.waiters.push(resolve));
  }

  private release(): void {
    const next = this.waiters.shift();
    if (next) next();
    else this.active--;
  }
}
