/**
 * Sync backend for a server book whose bytes live in the local library
 * (digest-linked download) opened on native.
 *
 * Progress is local-first: every save lands in the device record before the
 * best-effort server write, so a connection dying mid-session costs
 * nothing. Reads run a bounded push-and-merge first — the offline record
 * reaches the merge authority before the restore consults it, which is
 * what kills the reconnect race (open-from-server-entry used to restore
 * the stale server position and immediately re-save it with a fresh
 * timestamp, LWW-stomping a whole trip's reading).
 *
 * It masquerades as "beepub": highlights, AI, interaction and activity
 * flows stay server-shaped, exactly as they behave for streamed books.
 */
import { beepubSync } from "./beepub";
import { localSync } from "./local";
import type {
  HighlightDraft,
  HighlightPatch,
  ProgressSave,
  ProgressState,
  SyncBackend,
} from "./sync";

const MERGE_BUDGET_MS = 2500;

export function makeLinkedSync(localBookId: string): SyncBackend {
  return {
    kind: "beepub" as const,

    async getProgress(serverBookId: string): Promise<ProgressState | null> {
      try {
        // Dynamic import: readingSync pulls in stores the reading layer
        // shouldn't load eagerly.
        const { syncLocalBook } = await import("$lib/services/readingSync");
        await Promise.race([
          syncLocalBook(localBookId).catch(() => {}),
          new Promise((resolve) => setTimeout(resolve, MERGE_BUDGET_MS)),
        ]);
      } catch {
        // Merge is an optimization; both reads below still work.
      }
      try {
        return await beepubSync.getProgress(serverBookId);
      } catch {
        // Server unreachable (network died mid-session): the device record
        // is the freshest thing we have.
        return localSync.getProgress(localBookId);
      }
    },

    async saveProgress(
      serverBookId: string,
      state: ProgressSave,
    ): Promise<void> {
      // Local write first — it cannot fail on network, and readingSync
      // pushes it later if the server write below doesn't land.
      await localSync.saveProgress(localBookId, state);
      try {
        await beepubSync.saveProgress(serverBookId, state);
      } catch {
        // Offline mid-session: the record is safe locally.
      }
    },

    saveProgressBeacon(serverBookId: string, state: ProgressSave): void {
      localSync.saveProgressBeacon(localBookId, state);
      beepubSync.saveProgressBeacon(serverBookId, state);
    },

    listHighlights: (bookId: string) => beepubSync.listHighlights(bookId),
    createHighlight: (bookId: string, data: HighlightDraft) =>
      beepubSync.createHighlight(bookId, data),
    updateHighlight: (bookId: string, id: string, patch: HighlightPatch) =>
      beepubSync.updateHighlight(bookId, id, patch),
    deleteHighlight: (bookId: string, id: string) =>
      beepubSync.deleteHighlight(bookId, id),
  };
}
