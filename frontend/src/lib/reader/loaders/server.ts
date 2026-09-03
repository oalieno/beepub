/**
 * Server book loader: the `{ loadText, loadBlob, getSize }` contract the
 * foliate EPUB parser consumes, over the existing per-entry streamer
 * `GET /api/books/{id}/content/{path}`. The parser walks container.xml and
 * the OPF through this same interface, so nothing here knows EPUB
 * structure — it fetches zip entry paths.
 */
import type { BookPayload } from "$lib/reading/source";

export interface BookLoader {
  /** Entry text; null when the entry does not exist. The parser probes
   *  optional files (META-INF/encryption.xml, display-options, calibre
   *  bookmarks) and treats null as "absent". */
  loadText(href: string): Promise<string | null>;
  loadBlob(href: string): Promise<Blob>;
  /** Uncompressed byte size, 0 when unknown. The streamer exposes none;
   *  BeePub's progress uses spine text weights, not byte sizes. */
  getSize(href: string): number;
}

export class LoaderHttpError extends Error {
  constructor(
    public readonly href: string,
    public readonly status: number,
  ) {
    super(`${status} loading ${href}`);
    this.name = "LoaderHttpError";
  }
}

/**
 * @param root  Resource root ending in `/content/` (BookPayload.url).
 * @param authHeader  Fresh auth headers per request (native Bearer); null
 *   on web, where the HttpOnly cookie rides along same-origin.
 */
export function makeServerLoader(
  root: string,
  authHeader: (() => Record<string, string>) | null,
): BookLoader {
  const base = root.endsWith("/") ? root : root + "/";
  // Manifest hrefs arrive decoded (the parser decodeURI()s them); encode
  // per segment so spaces and CJK file names survive and `/` stays a
  // path separator for the `{path:path}` route.
  const urlFor = (href: string) =>
    base + href.split("/").map(encodeURIComponent).join("/");

  async function request(href: string): Promise<Response | null> {
    const res = await fetch(urlFor(href), {
      headers: authHeader ? authHeader() : undefined,
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new LoaderHttpError(href, res.status);
    return res;
  }

  return {
    async loadText(href) {
      const res = await request(href);
      return res ? res.text() : null;
    },
    async loadBlob(href) {
      const res = await request(href);
      if (res) return res.blob();
      // A missing image or stylesheet must not take the whole section
      // down: the parser awaits every referenced resource while rewriting
      // a section, so a rejection here would fail the chapter.
      console.warn(`[reader] missing entry in book: ${href}`);
      return new Blob([]);
    },
    getSize: () => 0,
  };
}

/** BookSource payload → loader. Whole-file payloads (downloaded/imported
 *  books) get their own jszip-backed loader in G2. */
export function loaderFromPayload(payload: BookPayload): BookLoader {
  if (payload.kind !== "stream") {
    throw new Error("Local books are not supported by the new reader yet");
  }
  return makeServerLoader(payload.url, payload.authHeader);
}
