/**
 * Download an OPDS acquisition link into the local library.
 *
 * The EPUB goes straight to a temp file via Filesystem.downloadFile (native
 * write, real progress events), is read back and handed to importLocalBook
 * as a File — the whole existing pipeline (digest dedup, parse, cover
 * extraction, chunked write, cleanup-on-failure) applies unchanged. The
 * body crosses the JS bridge once in each direction, same as the picker
 * import path.
 *
 * downloadFile is deprecated in favor of the @capacitor/file-transfer
 * plugin, but still ships in @capacitor/filesystem 8; staying on it avoids
 * a new native plugin. If Capacitor 9 drops it, file-transfer has the same
 * options/progress shape.
 */
import { Directory, Filesystem } from "@capacitor/filesystem";

import {
  importLocalBook,
  type LocalBookEntry,
} from "$lib/services/localLibrary";
import type { OpdsCatalog } from "$lib/services/opdsCatalogs";

import { authHeaders, OpdsError, type OpdsCredentials } from "./client";
import type { OpdsBookEntry } from "./parse";

function catalogCreds(catalog: OpdsCatalog): OpdsCredentials | undefined {
  if (!catalog.username) return undefined;
  return { username: catalog.username, password: catalog.password ?? "" };
}

function sanitizeFilename(title: string): string {
  const cleaned = title
    .replace(/[/\\:*?"<>|]/g, " ")
    .replace(/[\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || "book";
}

async function deleteTempQuiet(path: string): Promise<void> {
  try {
    await Filesystem.deleteFile({ path, directory: Directory.Cache });
  } catch {
    // Already gone
  }
}

/**
 * Rethrows DuplicateBookError / InvalidEpubError from importLocalBook and
 * OpdsError for transport failures. A non-2xx response may be persisted as
 * the file body by the plugin — that surfaces as InvalidEpubError, which
 * the caller already localizes.
 */
export async function downloadAndImport(
  entry: OpdsBookEntry,
  catalog: OpdsCatalog,
  onProgress?: (pct: number | null) => void,
): Promise<LocalBookEntry> {
  const epubUrl = entry.epubUrl;
  if (!epubUrl) throw new OpdsError("http", 404);
  const tempPath = `opds-tmp/${crypto.randomUUID()}.epub`;

  // One download runs at a time (the page queues), so filtering by url is
  // unambiguous. null pct = no content-length, indeterminate.
  const listener = await Filesystem.addListener("progress", (status) => {
    if (status.url !== epubUrl) return;
    onProgress?.(
      status.contentLength > 0
        ? Math.min(100, Math.round((status.bytes / status.contentLength) * 100))
        : null,
    );
  });

  try {
    try {
      await Filesystem.downloadFile({
        url: epubUrl,
        method: "GET",
        headers: authHeaders(catalogCreds(catalog)),
        path: tempPath,
        directory: Directory.Cache,
        progress: true,
        recursive: true,
      });
    } catch (err) {
      throw new OpdsError("network", undefined, err);
    }

    const result = await Filesystem.readFile({
      path: tempPath,
      directory: Directory.Cache,
    });
    let bytes: Uint8Array<ArrayBuffer>;
    if (typeof result.data === "string") {
      const binary = atob(result.data);
      bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
    } else {
      bytes = new Uint8Array(await result.data.arrayBuffer());
    }

    // The OPDS title stands in for the filename importLocalBook falls back
    // to when the EPUB carries no title (Content-Disposition isn't
    // reliably surfaced by the plugin).
    const file = new File([bytes], `${sanitizeFilename(entry.title)}.epub`, {
      type: "application/epub+zip",
    });
    return await importLocalBook(file);
  } finally {
    void listener.remove();
    await deleteTempQuiet(tempPath);
  }
}
