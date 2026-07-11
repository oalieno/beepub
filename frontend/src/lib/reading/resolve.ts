/**
 * Picks the source/sync pair for a book id — the reader's single
 * instantiation site calls this instead of hardcoding the BeePub pair.
 * Local books win: their ids are client-generated UUIDs, so a local
 * manifest hit is definitive. OPDS sources slot in here when they arrive.
 */
import { isNative } from "$lib/platform";
import { getLocalBook, type LocalBookEntry } from "$lib/services/localLibrary";

import { beepubSource, beepubSync } from "./beepub";
import { localSource, localSync } from "./local";
import type { BookSource } from "./source";
import type { SyncBackend } from "./sync";

export interface ResolvedReading {
  source: BookSource;
  sync: SyncBackend;
  /** Set when the book is a local import — carries display metadata the
   *  server would otherwise provide. */
  localEntry: LocalBookEntry | null;
}

export async function resolveReading(bookId: string): Promise<ResolvedReading> {
  if (isNative()) {
    try {
      const entry = await getLocalBook(bookId);
      if (entry) {
        return { source: localSource, sync: localSync, localEntry: entry };
      }
    } catch {
      // Fall through to the server pair.
    }
  }
  return { source: beepubSource, sync: beepubSync, localEntry: null };
}
