/**
 * Picks the source/sync pair for a book id — the reader's single
 * instantiation site calls this instead of hardcoding the BeePub pair.
 * Local books win: their ids are client-generated UUIDs, so a local
 * manifest hit is definitive. OPDS sources slot in here when they arrive.
 */
import { isLocalMode } from "$lib/api/client";
import { isNative } from "$lib/platform";
import { getKosyncAccount } from "$lib/services/kosyncAccount";
import {
  getLocalBook,
  getLocalBookLinks,
  type LocalBookEntry,
} from "$lib/services/localLibrary";

import { beepubSource, beepubSync } from "./beepub";
import { localSource, localSourceFor, localSync } from "./local";
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
        // External kosync is local-mode-only: in server mode the BeePub
        // server IS the kosync server (readingSync bridges through it),
        // so the account lies dormant until the user switches modes.
        if (isLocalMode()) {
          try {
            const account = await getKosyncAccount();
            if (account) {
              const { makeKosyncSync } = await import("./kosync");
              return {
                source: localSource,
                sync: makeKosyncSync(entry, account),
                localEntry: entry,
              };
            }
          } catch {
            // Plain local reading must never be blocked by sync config.
          }
        }
        return { source: localSource, sync: localSync, localEntry: entry };
      }
    } catch {
      // Fall through to the server pair.
    }
    // Capability, not entry point: a server book with a digest-linked
    // downloaded copy reads its bytes from disk — fast on a slow network
    // — and its progress goes local-first through the linked sync (which
    // masquerades as beepub, so the page's server-shaped flows all hold).
    try {
      const links = await getLocalBookLinks();
      const localId = Object.keys(links).find((k) => links[k] === bookId);
      if (localId && (await getLocalBook(localId))) {
        const { makeLinkedSync } = await import("./linked");
        return {
          source: localSourceFor(localId),
          sync: makeLinkedSync(localId),
          localEntry: null,
        };
      }
    } catch {
      // Fall through to streaming.
    }
  }
  return { source: beepubSource, sync: beepubSync, localEntry: null };
}
