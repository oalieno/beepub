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
 * Highlights are local-first too: they live in the device records the
 * background sync already merges both ways (per-id LWW with tombstones,
 * ids kept by the server), so marking a downloaded book needs no network
 * — each write lands on the device, then a push goes up behind it.
 *
 * It masquerades as "beepub": AI, interaction and activity flows stay
 * server-shaped, exactly as they behave for streamed books.
 */
import { beepubSync } from "./beepub";
import { localSync } from "./local";
import type { HighlightOut } from "$lib/types";
import type {
  HighlightDraft,
  HighlightPatch,
  ProgressSave,
  ProgressState,
  SyncBackend,
} from "./sync";

const MERGE_BUDGET_MS = 2500;
/** A read the server hasn't answered by now falls back to the device —
 *  a dying connection must not hold the reader on its loading screen. */
const READ_BUDGET_MS = 4000;

const timedOut = Symbol("timedOut");

function withBudget<T>(
  work: Promise<T>,
  ms: number,
): Promise<T | typeof timedOut> {
  return Promise.race([
    work,
    new Promise<typeof timedOut>((resolve) =>
      setTimeout(() => resolve(timedOut), ms),
    ),
  ]);
}

export function makeLinkedSync(localBookId: string): SyncBackend {
  /** One bounded push-and-merge per open, shared by the progress and
   *  highlight reads the reader issues side by side. */
  let merged: Promise<void> | null = null;
  function mergeFirst(): Promise<void> {
    merged ??= (async () => {
      try {
        // Dynamic import: readingSync pulls in stores the reading layer
        // shouldn't load eagerly.
        const { syncLocalBook } = await import("$lib/services/readingSync");
        await withBudget(
          syncLocalBook(localBookId).catch(() => {}),
          MERGE_BUDGET_MS,
        );
      } catch {
        // Merge is an optimization; the reads after it still work.
      }
    })();
    return merged;
  }

  function pushSoon(): void {
    void import("$lib/services/readingSync")
      .then(({ pushLocalBook }) => pushLocalBook(localBookId))
      .catch(() => {
        // Offline: the foreground/online triggers push it later.
      });
  }

  /** Device records carry the local id; the reader speaks server ids. */
  const asServer = (h: HighlightOut, serverBookId: string): HighlightOut => ({
    ...h,
    book_id: serverBookId,
  });

  return {
    kind: "beepub" as const,

    async getProgress(serverBookId: string): Promise<ProgressState | null> {
      await mergeFirst();
      try {
        const remote = await withBudget(
          beepubSync.getProgress(serverBookId),
          READ_BUDGET_MS,
        );
        if (remote !== timedOut) return remote;
      } catch {
        // Server unreachable (network died mid-session).
      }
      // The device record is the freshest thing we have.
      return localSync.getProgress(localBookId);
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

    async listHighlights(serverBookId: string): Promise<HighlightOut[]> {
      // After the merge, the device records hold the server's marks too.
      await mergeFirst();
      const all = await localSync.listHighlights(localBookId);
      return all.map((h) => asServer(h, serverBookId));
    },

    async createHighlight(
      serverBookId: string,
      data: HighlightDraft,
    ): Promise<HighlightOut> {
      const created = await localSync.createHighlight(localBookId, data);
      pushSoon();
      return asServer(created, serverBookId);
    },

    async updateHighlight(
      serverBookId: string,
      id: string,
      patch: HighlightPatch,
    ): Promise<HighlightOut> {
      const updated = await localSync.updateHighlight(localBookId, id, patch);
      pushSoon();
      return asServer(updated, serverBookId);
    },

    async deleteHighlight(_serverBookId: string, id: string): Promise<void> {
      await localSync.deleteHighlight(localBookId, id);
      pushSoon();
    },
  };
}
