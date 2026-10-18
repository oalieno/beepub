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
  // A book made on a case-insensitive file system may name "style/a.css"
  // what the zip holds as "Style/a.css": failing the exact name, the
  // name in another case is taken.
  let folded: Map<string, string> | null = null;
  const find = (href: string) => {
    const exact = zip.file(href);
    if (exact) return exact;
    folded ??= new Map(
      Object.keys(zip.files).map((name) => [name.toLowerCase(), name]),
    );
    const other = folded.get(href.toLowerCase());
    return other ? zip.file(other) : null;
  };
  return {
    async loadText(href) {
      const entry = find(href);
      return entry ? entry.async("string") : null;
    },
    async loadBlob(href) {
      const entry = find(href);
      if (entry) return entry.async("blob");
      // Same stance as the server loader: a missing image or stylesheet
      // must not take the whole section down.
      console.warn(`[reader] missing entry in book: ${href}`);
      return new Blob([]);
    },
    getSize: () => 0,
  };
}
