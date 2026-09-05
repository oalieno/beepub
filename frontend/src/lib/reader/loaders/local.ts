/**
 * Local book loader: the BookLoader contract over a whole EPUB file held
 * in memory — an imported or downloaded copy read back from the device's
 * Directory.Data. jszip parses the central directory once; entries
 * inflate on demand, so a large book costs its file size in memory and
 * nothing more up front.
 */
import JSZip from "jszip";

import type { BookLoader } from "./types";

export async function makeLocalLoader(data: ArrayBuffer): Promise<BookLoader> {
  const zip = await JSZip.loadAsync(data);
  // Manifest hrefs arrive decoded and resolved against the OPF path, and
  // jszip stores entry names decoded too, so lookups are exact. `file()`
  // answers null for directories as well as missing names.
  return {
    async loadText(href) {
      const entry = zip.file(href);
      return entry ? entry.async("string") : null;
    },
    async loadBlob(href) {
      const entry = zip.file(href);
      if (entry) return entry.async("blob");
      // Same stance as the server loader: a missing image or stylesheet
      // must not take the whole section down.
      console.warn(`[reader] missing entry in book: ${href}`);
      return new Blob([]);
    },
    getSize: () => 0,
  };
}
