/**
 * Download an EPUB over HTTP into the local library — the shared core
 * behind OPDS acquisition links and "download from the BeePub server".
 *
 * The file goes straight to a temp path via Filesystem.downloadFile
 * (native write, real progress events), is read back and handed to
 * importLocalBook as a File — the whole existing pipeline (digest dedup,
 * parse, cover extraction, chunked write, cleanup-on-failure) applies
 * unchanged. The body crosses the JS bridge once in each direction, same
 * as the picker import path.
 *
 * downloadFile is deprecated in favor of the @capacitor/file-transfer
 * plugin, but still ships in @capacitor/filesystem 8; staying on it avoids
 * a new native plugin. If Capacitor 9 drops it, file-transfer has the same
 * options/progress shape.
 *
 * Transport errors from the plugin propagate raw — callers wrap them in
 * their own error vocabulary. Import errors (DuplicateBookError,
 * InvalidEpubError) rethrow as-is; a non-2xx response may be persisted as
 * the file body by the plugin, which surfaces as InvalidEpubError.
 */
import { Directory, Filesystem } from "@capacitor/filesystem";

import {
  importLocalBook,
  type LocalBookEntry,
} from "$lib/services/localLibrary";

export function sanitizeFilename(title: string): string {
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

export async function downloadEpubToLibrary(options: {
  url: string;
  headers: Record<string, string>;
  /** Fallback title when the EPUB carries none (Content-Disposition isn't
   *  reliably surfaced by the plugin). */
  title: string;
  onProgress?: (pct: number | null) => void;
}): Promise<LocalBookEntry> {
  const tempPath = `epub-dl/${crypto.randomUUID()}.epub`;

  // One download runs at a time (callers queue), so filtering by url is
  // unambiguous. null pct = no content-length, indeterminate.
  const listener = await Filesystem.addListener("progress", (status) => {
    if (status.url !== options.url) return;
    options.onProgress?.(
      status.contentLength > 0
        ? Math.min(100, Math.round((status.bytes / status.contentLength) * 100))
        : null,
    );
  });

  try {
    await Filesystem.downloadFile({
      url: options.url,
      method: "GET",
      headers: options.headers,
      path: tempPath,
      directory: Directory.Cache,
      progress: true,
      recursive: true,
    });

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

    const file = new File([bytes], `${sanitizeFilename(options.title)}.epub`, {
      type: "application/epub+zip",
    });
    return await importLocalBook(file);
  } finally {
    void listener.remove();
    await deleteTempQuiet(tempPath);
  }
}
