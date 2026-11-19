/**
 * Server book loader: the BookLoader contract over the existing per-entry
 * streamer `GET /api/books/{id}/content/{path}`.
 */
import type { BookLoader } from "./types";

/** How long a request may go without a byte before it is given up. */
const STALL_MS = 15_000;

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

  /** One request, given up when it stalls: the headers, and then every
   *  chunk of the body, have STALL_MS to arrive. A slow link that keeps
   *  delivering is never cut off; one that has gone silent (a phone that
   *  left its network without the socket noticing) rejects instead of
   *  holding the chapter behind it for good. */
  async function request(href: string): Promise<Uint8Array[] | null> {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const alive = () => {
      clearTimeout(timer);
      timer = setTimeout(() => controller.abort(), STALL_MS);
    };
    alive();
    try {
      const res = await fetch(urlFor(href), {
        headers: authHeader ? authHeader() : undefined,
        signal: controller.signal,
      });
      if (res.status === 404) return null;
      if (!res.ok) throw new LoaderHttpError(href, res.status);
      alive();
      const reader = res.body?.getReader?.();
      // (A fetch whose body is not a stream: the one deadline covers it.)
      if (!reader) return [new Uint8Array(await res.arrayBuffer())];
      const chunks: Uint8Array[] = [];
      for (;;) {
        const { done, value } = await reader.read();
        if (done) return chunks;
        if (value) chunks.push(value);
        alive();
      }
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    async loadText(href) {
      const chunks = await request(href);
      if (!chunks) return null;
      // As Response.text() reads it: UTF-8, a leading BOM dropped.
      const decoder = new TextDecoder();
      let text = "";
      for (const chunk of chunks)
        text += decoder.decode(chunk, { stream: true });
      return text + decoder.decode();
    },
    async loadBlob(href) {
      const chunks = await request(href);
      if (chunks) return new Blob(chunks as BlobPart[]);
      // A missing image or stylesheet must not take the whole section
      // down: the parser awaits every referenced resource while rewriting
      // a section, so a rejection here would fail the chapter.
      console.warn(`[reader] missing entry in book: ${href}`);
      return new Blob([]);
    },
    getSize: () => 0,
  };
}
