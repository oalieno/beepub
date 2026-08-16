/**
 * BeePub-server implementations of BookSource and SyncBackend. Everything
 * delegates to the existing API layer — wire formats and URLs stay owned
 * by lib/api; this module only translates Locator-shaped state at the
 * boundary.
 */
import { booksApi } from "$lib/api/books";
import { apiBase, getAuthHeader } from "$lib/api/client";

import { cfiOf, locatorFromCfi } from "./locator";
import type { BookPayload, BookSource } from "./source";
import type {
  HighlightDraft,
  HighlightPatch,
  ProgressSave,
  ProgressState,
  SyncBackend,
} from "./sync";

class BeepubBookSource implements BookSource {
  readonly kind = "beepub" as const;

  async openBook(bookId: string): Promise<BookPayload> {
    // Always streams: downloaded copies live in the local library and
    // resolve to the local source before this one is ever consulted.
    const hasAuth = Object.keys(getAuthHeader()).length > 0;
    return {
      kind: "stream",
      // apiBase() is read lazily per call — the server URL can change at
      // runtime; never capture it in the singleton.
      url: `${apiBase()}/books/${bookId}/content/`,
      // A function, not a snapshot: the access token can rotate
      // mid-session and every later XHR must pick up the new one.
      authHeader: hasAuth ? getAuthHeader : null,
    };
  }

}

/** Locator/ProgressSave → the exact wire body PUT /progress expects.
 *  Unit boundary: wire percentage is 0..100, totalProgression is 0..1;
 *  totalProgression undefined maps to percentage null ("keep stored"),
 *  never 0. */
function toWireProgress(state: ProgressSave) {
  const totalProgression = state.locator.locations.totalProgression;
  return {
    cfi: cfiOf(state.locator) ?? "",
    percentage: totalProgression === undefined ? null : totalProgression * 100,
    current_page: state.locator.locations.position ?? 0,
    font_size: state.fontSize,
    section_index: state.sectionIndex,
    section_page: state.sectionPage,
    section_page_counts: state.sectionPageCounts,
    total_pages: state.totalPages,
    xpointer: state.xpointer ?? undefined,
    track_activity: state.trackActivity,
  };
}

class BeepubSyncBackend implements SyncBackend {
  readonly kind = "beepub" as const;

  async getProgress(bookId: string): Promise<ProgressState | null> {
    const p = await booksApi.getProgress(bookId);
    return {
      locator: p.cfi
        ? locatorFromCfi(p.cfi, {
            totalProgression:
              p.percentage == null ? undefined : p.percentage / 100,
            position: p.current_page ?? undefined,
          })
        : null,
      fontSize: p.font_size,
      sectionIndex: p.section_index,
      sectionPage: p.section_page,
      sectionPageCounts: p.section_page_counts,
      totalPages: p.total_pages,
      lastReadAt: p.last_read_at,
      devicePosition: p.kosync
        ? {
            percentage: p.kosync.percentage,
            device: p.kosync.device,
            sectionIndex: p.kosync.section_index ?? null,
            xpointer: p.kosync.xpointer ?? null,
          }
        : null,
    };
  }

  async saveProgress(bookId: string, state: ProgressSave): Promise<void> {
    await booksApi.updateProgress(bookId, toWireProgress(state));
  }

  saveProgressBeacon(bookId: string, state: ProgressSave): void {
    // keepalive lets the PUT survive page unload; sendBeacon can't set
    // Content-Type/Authorization, so a keepalive fetch it is.
    fetch(`${apiBase()}/books/${bookId}/progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify(toWireProgress(state)),
      keepalive: true,
    });
  }

  listHighlights(bookId: string) {
    return booksApi.getHighlights(bookId);
  }

  createHighlight(bookId: string, data: HighlightDraft) {
    return booksApi.createHighlight(bookId, data);
  }

  updateHighlight(bookId: string, highlightId: string, patch: HighlightPatch) {
    return booksApi.updateHighlight(bookId, highlightId, patch);
  }

  async deleteHighlight(bookId: string, highlightId: string): Promise<void> {
    await booksApi.deleteHighlight(bookId, highlightId);
  }
}

export const beepubSource: BookSource = new BeepubBookSource();
export const beepubSync: SyncBackend = new BeepubSyncBackend();
