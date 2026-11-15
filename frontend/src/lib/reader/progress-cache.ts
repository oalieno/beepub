/**
 * The last place read in a book, kept on this device.
 *
 * The server holds the position; this is the copy used when it cannot be
 * asked (an installed web app resumed without a connection). Both
 * readers — the one for text and the one for image books — write it on
 * every move and read it only when the server gave no answer, so a book
 * opens where it was left either way.
 */

export interface CachedProgress {
  cfi: string | null;
  /** 0..100 */
  percentage: number | null;
  /** Whatever else the reader that wrote it wanted back. */
  extra: Record<string, unknown>;
}

const key = (bookId: string) => `reader-progress-${bookId}`;

/** Keep the position. Storage that is full or unavailable is not an
 *  error: the server still has it. */
export function rememberProgress(
  bookId: string,
  cfi: string | null,
  percentage: number,
  extra: Record<string, unknown> = {},
): void {
  try {
    localStorage.setItem(
      key(bookId),
      JSON.stringify({ ...extra, cfi, percentage }),
    );
  } catch {
    // storage full or unavailable
  }
}

/** The position kept for the book, or null when there is none that can
 *  be read. */
export function recallProgress(bookId: string): CachedProgress | null {
  try {
    const raw = localStorage.getItem(key(bookId));
    if (!raw) return null;
    const { cfi, percentage, ...extra } = JSON.parse(raw) as Record<
      string,
      unknown
    >;
    return {
      cfi: typeof cfi === "string" ? cfi : null,
      percentage: typeof percentage === "number" ? percentage : null,
      extra,
    };
  } catch {
    return null;
  }
}
