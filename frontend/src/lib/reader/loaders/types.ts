/**
 * The book loader contract the foliate EPUB parser consumes:
 * `{ loadText, loadBlob, getSize }`. The parser walks container.xml and
 * the OPF through this same interface, so no loader knows EPUB structure
 * — each one answers zip entry paths from wherever the bytes live
 * (server streamer, whole file on the device).
 */
export interface BookLoader {
  /** Entry text; null when the entry does not exist. The parser probes
   *  optional files (META-INF/encryption.xml, display-options, calibre
   *  bookmarks) and treats null as "absent". */
  loadText(href: string): Promise<string | null>;
  /** Entry bytes. The parser's resource loader wraps the result in a Blob
   *  typed by the manifest media type, so the loader's own type may be
   *  empty. */
  loadBlob(href: string): Promise<Blob>;
  /** Uncompressed byte size, 0 when unknown. BeePub's progress uses spine
   *  text weights, not byte sizes, so nothing downstream depends on it. */
  getSize(href: string): number;
}
