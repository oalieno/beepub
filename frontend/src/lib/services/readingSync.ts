/**
 * Background sync of linked local books with the BeePub server.
 *
 * A local book links to a server book by file digest (partial md5); once
 * linked, its reading state merges bidirectionally: highlights by per-id
 * updated_at last-write-wins with tombstone union, progress by a single
 * last_read_at winner. The server is the merge authority — this module
 * pushes the full local state, then folds the post-merge response back
 * into the local records.
 *
 * Known edge: the local store is single-user (records are not scoped per
 * account), so two accounts on the same server sharing one device would
 * cross-pollinate through sync. Acceptable for personal devices; the fix,
 * if ever needed, is user-scoping the links key.
 */
import { get } from "svelte/store";

import { booksApi } from "$lib/api/books";
import { hasServerUrl } from "$lib/api/client";
import { isNative } from "$lib/platform";
import {
  readLocalHighlightRecords,
  readLocalProgress,
  writeLocalHighlightRecords,
  writeLocalProgress,
  type LocalHighlightRecord,
  type LocalProgressRecord,
} from "$lib/reading/local";
import {
  clearLocalBookLink,
  getLocalBookLinks,
  listLocalBooks,
  setLocalBookLink,
  type LocalBookEntry,
} from "$lib/services/localLibrary";
import { getIsOnline, isOnline } from "$lib/services/network";
import { authStore } from "$lib/stores/auth";
import type { BookSyncResponse, SyncProgressIn } from "$lib/types";

const FULL_SYNC_COOLDOWN_MS = 30_000;

let initialized = false;
let fullSyncInFlight: Promise<void> | null = null;
let lastFullSyncAt = 0;
const perBookInFlight = new Map<string, Promise<void>>();

function canSync(): boolean {
  // The user guard matters: a background trigger while logged out would
  // 401 and the api client's persistent-401 handler redirects to /login.
  return (
    isNative() &&
    hasServerUrl() &&
    get(authStore).user !== null &&
    getIsOnline()
  );
}

/** Register the reconnect trigger. Idempotent; call once at app start. */
export function initReadingSync(): void {
  if (initialized) return;
  initialized = true;
  let prev = getIsOnline();
  isOnline.subscribe((online) => {
    if (online && !prev) void linkAndSyncAll();
    prev = online;
  });
}

/** Link every unlinked local book that matches a server book by digest,
 *  then sync all linked books. Coalesced and rate-limited. */
export function linkAndSyncAll(opts?: { force?: boolean }): Promise<void> {
  if (!canSync()) return Promise.resolve();
  if (fullSyncInFlight) return fullSyncInFlight;
  if (!opts?.force && Date.now() - lastFullSyncAt < FULL_SYNC_COOLDOWN_MS) {
    return Promise.resolve();
  }
  fullSyncInFlight = (async () => {
    try {
      const books = await listLocalBooks();
      if (books.length === 0) return;
      const links = await getLocalBookLinks();
      const unlinked = books.filter((b) => !links[b.id]);
      if (unlinked.length > 0) {
        const { matches } = await booksApi.lookupByDigest(
          unlinked.map((b) => b.digest),
        );
        for (const book of unlinked) {
          const match = matches[book.digest];
          if (match) {
            await setLocalBookLink(book.id, match.id);
            links[book.id] = match.id;
          }
        }
      }
      // Sequentially — local shelves are small, and a burst of parallel
      // merges would stampede NAS-class servers for no gain.
      for (const book of books) {
        if (links[book.id]) await syncLocalBook(book.id);
      }
      lastFullSyncAt = Date.now();
    } catch (err) {
      console.warn("readingSync: full sync failed", err);
    } finally {
      fullSyncInFlight = null;
    }
  })();
  return fullSyncInFlight;
}

/** Post-import hook: try to link one book and sync it. True = linked. */
export async function linkAndSyncBook(entry: LocalBookEntry): Promise<boolean> {
  if (!canSync()) return false;
  try {
    const links = await getLocalBookLinks();
    if (!links[entry.id]) {
      const { matches } = await booksApi.lookupByDigest([entry.digest]);
      const match = matches[entry.digest];
      if (!match) return false;
      await setLocalBookLink(entry.id, match.id);
    }
    await syncLocalBook(entry.id);
    return true;
  } catch (err) {
    console.warn("readingSync: link failed", err);
    return false;
  }
}

/** Sync one local book's reading state. No-op when unlinked; re-entrant
 *  calls share the in-flight promise. */
export function syncLocalBook(localBookId: string): Promise<void> {
  const existing = perBookInFlight.get(localBookId);
  if (existing) return existing;
  const run = doSync(localBookId).finally(() =>
    perBookInFlight.delete(localBookId),
  );
  perBookInFlight.set(localBookId, run);
  return run;
}

function toSyncProgress(record: LocalProgressRecord): SyncProgressIn {
  return {
    cfi: record.cfi,
    percentage: record.percentage,
    current_page: record.current_page,
    font_size: record.font_size,
    section_index: record.section_index,
    section_page: record.section_page,
    section_page_counts: record.section_page_counts,
    total_pages: record.total_pages,
    xpointer: record.xpointer,
    last_read_at: record.last_read_at,
  };
}

async function doSync(localBookId: string): Promise<void> {
  if (!canSync()) return;
  const links = await getLocalBookLinks();
  const serverBookId = links[localBookId];
  if (!serverBookId) return;

  const progress = await readLocalProgress(localBookId);
  const highlights = await readLocalHighlightRecords(localBookId);

  let response: BookSyncResponse;
  try {
    response = await booksApi.syncReadingState(serverBookId, {
      progress: progress && progress.cfi ? toSyncProgress(progress) : null,
      highlights,
    });
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status === 404 || status === 403) {
      // The server book is gone or access was revoked. Unlink; the next
      // full pass re-resolves by digest (self-healing for re-uploads).
      await clearLocalBookLink(localBookId);
    } else {
      console.warn("readingSync: sync failed", err);
    }
    return;
  }

  await applyHighlights(localBookId, response);
  await applyProgress(localBookId, response);
}

async function applyHighlights(
  localBookId: string,
  response: BookSyncResponse,
): Promise<void> {
  // Merge by id rather than replacing wholesale: highlights written while
  // the request was in flight, and items the server never accepted (e.g.
  // a foreign-id collision), must survive to be pushed next time.
  const fresh = await readLocalHighlightRecords(localBookId);
  const byId = new Map<string, LocalHighlightRecord>();
  for (const remote of response.highlights) {
    byId.set(remote.id, { ...remote, deleted_at: remote.deleted_at ?? null });
  }
  for (const local of fresh) {
    const remote = byId.get(local.id);
    // Date.parse, never string compare: the server serializes +00:00 with
    // microseconds, local records use Z with milliseconds. Ties keep the
    // server copy (the merge authority's tie rule).
    if (
      !remote ||
      Date.parse(local.updated_at) > Date.parse(remote.updated_at)
    ) {
      byId.set(local.id, local);
    }
  }
  const merged = [...byId.values()].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  );
  await writeLocalHighlightRecords(localBookId, merged);
}

async function applyProgress(
  localBookId: string,
  response: BookSyncResponse,
): Promise<void> {
  const dict = response.progress;
  if (!dict || (dict.cfi == null && dict.percentage == null)) return;
  if (!dict.last_read_at) return;
  const fresh = await readLocalProgress(localBookId);
  // Covers both the echo of our own win and an in-flight reader save.
  if (
    fresh &&
    Date.parse(fresh.last_read_at) >= Date.parse(dict.last_read_at)
  ) {
    return;
  }
  const record: LocalProgressRecord = {
    // An empty cfi can happen when the dict was written by the kosync
    // bridge alone; getProgress treats it as "no locator", which leaves
    // the device marker auto-jump eligible.
    cfi: dict.cfi ?? "",
    percentage: dict.percentage ?? fresh?.percentage ?? null,
    current_page: dict.current_page ?? fresh?.current_page ?? 0,
    font_size: dict.font_size ?? fresh?.font_size ?? 16,
    section_index: dict.section_index ?? fresh?.section_index ?? 0,
    section_page: dict.section_page ?? fresh?.section_page ?? 0,
    section_page_counts:
      dict.section_page_counts ?? fresh?.section_page_counts ?? [],
    total_pages: dict.total_pages ?? fresh?.total_pages ?? 0,
    xpointer: dict.xpointer ?? null,
    last_read_at: dict.last_read_at,
    updated_at: dict.last_read_at,
    // The server-side kosync marker rides along, so the reader can offer
    // "jump to the e-reader position" for local books too.
    kosync: dict.kosync
      ? {
          percentage: dict.kosync.percentage,
          device: dict.kosync.device,
          synced_at: dict.kosync.synced_at,
          section_index: dict.kosync.section_index ?? null,
          xpointer: dict.kosync.xpointer ?? null,
        }
      : null,
  };
  await writeLocalProgress(localBookId, record);
}
