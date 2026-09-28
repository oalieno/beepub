/**
 * OPDS through the BeePub server — the server library's catalogs. The
 * server holds the list and the credentials and fetches on our behalf
 * (browsers can't: catalogs rarely allow CORS); parsing stays here, the
 * same parser the device catalogs use, fed the final URL the server
 * reached so relative links resolve right.
 */
import { apiBase, del, get, post, put } from "$lib/api/client";
import type { BookOut } from "$lib/types";

import { OpdsError } from "./errors";
import {
  parseOpdsFeed,
  parseOpenSearchDescription,
  type OpdsBookEntry,
  type OpdsFeed,
} from "./parse";

export interface ServerCatalog {
  id: string;
  name: string;
  url: string;
  /** Admins only. */
  username: string | null;
  has_credentials: boolean;
}

export interface ServerCatalogInput {
  name: string;
  url: string;
  username?: string;
  /** On update, omitted keeps the stored password. */
  password?: string;
}

const base = "/opds-catalogs";

export const serverCatalogs = {
  list: () => get(base) as Promise<ServerCatalog[]>,
  get: (id: string) => get(`${base}/${id}`) as Promise<ServerCatalog>,
  create: (input: ServerCatalogInput) =>
    post(base, input) as Promise<ServerCatalog>,
  update: (id: string, input: ServerCatalogInput) =>
    put(`${base}/${id}`, input) as Promise<ServerCatalog>,
  remove: (id: string) => del(`${base}/${id}`),
};

/** The server's "opds:<kind>" failures as OpdsError; anything else (the
 *  server itself unreachable) is a network error. */
function toOpdsError(err: unknown): OpdsError {
  const message = (err as Error).message ?? "";
  const status = (err as { status?: number }).status;
  const kind = /^opds:(\w+)/.exec(message)?.[1];
  if (kind === "auth" || kind === "blocked") return new OpdsError(kind, status);
  if (status === 404) return new OpdsError("http", 404, err);
  return new OpdsError(kind === "http" ? "http" : "network", status, err);
}

async function fetchText(
  catalogId: string,
  url?: string,
): Promise<{ url: string; body: string }> {
  const qs = url ? `?url=${encodeURIComponent(url)}` : "";
  try {
    return (await get(`${base}/${catalogId}/feed${qs}`)) as {
      url: string;
      body: string;
    };
  } catch (err) {
    throw toOpdsError(err);
  }
}

export async function fetchServerFeed(
  catalogId: string,
  url?: string,
): Promise<OpdsFeed> {
  const res = await fetchText(catalogId, url);
  try {
    return parseOpdsFeed(res.body, res.url, { allowHttp: true });
  } catch (err) {
    throw new OpdsError("parse", undefined, err);
  }
}

export async function fetchServerSearchTemplate(
  catalogId: string,
  descUrl: string,
): Promise<string | null> {
  try {
    const res = await fetchText(catalogId, descUrl);
    return parseOpenSearchDescription(res.body, res.url, { allowHttp: true });
  } catch {
    return null;
  }
}

/** A catalog image through the server (for use with authedSrc). */
export function serverImageUrl(catalogId: string, url: string): string {
  return `${apiBase()}${base}/${catalogId}/image?url=${encodeURIComponent(url)}`;
}

// What the server ingests, best first: EPUB is read as-is, the rest are
// converted.
const IMPORTABLE = [
  "application/epub+zip",
  "application/x-mobi8-ebook",
  "application/vnd.amazon.ebook",
  "application/x-mobipocket-ebook",
  "application/vnd.comicbook+zip",
  "application/x-cbz",
  "text/plain",
];

/** The acquisition link the server should import, or null when the entry
 *  offers nothing it reads (PDF, audiobooks, …). */
export function importableDownload(
  entry: OpdsBookEntry,
): { href: string; type: string } | null {
  let best: { href: string; type: string } | null = null;
  let bestRank = IMPORTABLE.length;
  for (const d of entry.downloads) {
    const rank = IMPORTABLE.indexOf(d.type.split(";")[0].trim().toLowerCase());
    if (rank !== -1 && rank < bestRank) {
      best = d;
      bestRank = rank;
    }
  }
  return best;
}

export async function importToServer(
  catalogId: string,
  entry: OpdsBookEntry,
  libraryId: string,
): Promise<{ status: "imported" | "duplicate"; book: BookOut }> {
  const download = importableDownload(entry);
  if (!download) throw new OpdsError("http", 415);
  try {
    return (await post(`${base}/${catalogId}/import`, {
      url: download.href,
      library_id: libraryId,
      title: entry.title,
      type: download.type,
    })) as { status: "imported" | "duplicate"; book: BookOut };
  } catch (err) {
    if ((err as { status?: number }).status === 415) throw err;
    throw toOpdsError(err);
  }
}
