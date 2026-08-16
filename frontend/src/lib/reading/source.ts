/**
 * BookSource answers "where do this book's bytes come from". The reader is
 * agnostic: it either receives the whole file or a resource root it can
 * stream section-by-section (epub.js openAs: "directory").
 */
export type BookPayload =
  | { kind: "bytes"; data: ArrayBuffer }
  | {
      kind: "stream";
      /** Resource root for epub.js openAs: "directory". */
      url: string;
      /** Fresh auth headers per request — a function because the token can
       *  rotate mid-session; null = no auth needed. */
      authHeader: (() => Record<string, string>) | null;
    };

export interface BookSource {
  readonly kind: "beepub" | "local" | "opds";
  /** Resolve how to open the book: whole-file bytes or a streamable root. */
  openBook(bookId: string): Promise<BookPayload>;
}
