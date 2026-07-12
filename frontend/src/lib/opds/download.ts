/**
 * Download an OPDS acquisition link into the local library — a thin
 * wrapper over the shared EPUB download core that supplies OPDS Basic
 * auth and maps transport failures into the OPDS error vocabulary.
 */
import type { LocalBookEntry } from "$lib/services/localLibrary";
import { downloadEpubToLibrary } from "$lib/services/epubDownload";
import {
  DuplicateBookError,
  InvalidEpubError,
} from "$lib/services/localLibrary";
import type { OpdsCatalog } from "$lib/services/opdsCatalogs";

import { authHeaders, OpdsError, type OpdsCredentials } from "./client";
import type { OpdsBookEntry } from "./parse";

function catalogCreds(catalog: OpdsCatalog): OpdsCredentials | undefined {
  if (!catalog.username) return undefined;
  return { username: catalog.username, password: catalog.password ?? "" };
}

/**
 * Rethrows DuplicateBookError / InvalidEpubError from importLocalBook and
 * OpdsError for transport failures.
 */
export async function downloadAndImport(
  entry: OpdsBookEntry,
  catalog: OpdsCatalog,
  onProgress?: (pct: number | null) => void,
): Promise<LocalBookEntry> {
  const epubUrl = entry.epubUrl;
  if (!epubUrl) throw new OpdsError("http", 404);
  try {
    return await downloadEpubToLibrary({
      url: epubUrl,
      headers: authHeaders(catalogCreds(catalog)),
      title: entry.title,
      onProgress,
    });
  } catch (err) {
    if (err instanceof DuplicateBookError || err instanceof InvalidEpubError)
      throw err;
    throw new OpdsError("network", undefined, err);
  }
}
