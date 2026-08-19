/**
 * Background sync of linked local books with the BeePub server.
 *
 * A local book links to a server book by file digest (partial md5); once
 * linked, its reading state merges bidirectionally: highlights by per-id
 * updated_at last-write-wins with tombstone union, progress by a single
 * last_read_at winner, and the reading-status group by its own LWW stamp.
 * The server is the merge authority — this module pushes the full local
 * state, then folds the post-merge response back into the local records.
 *
 * Known edge: the local store is single-user (records are not scoped per
 * account), so two accounts on the same server sharing one device would
 * cross-pollinate through sync. Acceptable for personal devices; the fix,
 * if ever needed, is user-scoping the links key.
 */
import { get, writable } from "svelte/store";

import { booksApi } from "$lib/api/books";
import { hasServerUrl, isLocalMode } from "$lib/api/client";
import { isNative } from "$lib/platform";
import {
  readLocalHighlightRecords,
  readLocalInteraction,
  readLocalProgress,
  writeLocalHighlightRecords,
  writeLocalInteraction,
  writeLocalProgress,
  type LocalHighlightRecord,
  type LocalInteractionRecord,
  type LocalProgressRecord,
} from "$lib/reading/local";
import {
  clearLocalBookLink,
  getLocalBook,
  getLocalBookLinks,
  listLocalBooks,
  setLocalBookLink,
  updateLocalBookMeta,
  type LocalBookEntry,
} from "$lib/services/localLibrary";
import { getIsOnline, isOnline } from "$lib/services/network";
import { pushLedger } from "$lib/services/readingLedger";
import { authStore } from "$lib/stores/auth";
import { refreshLinkedBookIds } from "$lib/stores/linkedBooks";
import type {
  BookSyncResponse,
  SyncInteractionIn,
  SyncProgressIn,
} from "$lib/types";

const FULL_SYNC_COOLDOWN_MS = 30_000;

/** Bumps when a full sync pass finishes — progress surfaces that were
 *  already mounted (home shelf, book detail) refetch on it. Pages opened
 *  after the pass fetch fresh anyway; without this signal a page you are
 *  looking at keeps pre-sync numbers until something remounts it. */
export const readingSyncStamp = writable(0);

let initialized = false;
let fullSyncInFlight: Promise<void> | null = null;
let lastFullSyncAt = 0;
const perBookInFlight = new Map<string, Promise<void>>();

function canSync(): boolean {
  // The user guard matters: a background trigger while logged out would
  // 401 and the api client's persistent-401 handler redirects to /login.
  return (
    isNative() &&
    !isLocalMode() &&
    hasServerUrl() &&
    get(authStore).user !== null &&
    getIsOnline()
  );
}

/** Register the background sync triggers. Idempotent; call once at app
 *  start (browser context only). */
export function initReadingSync(): void {
  if (initialized) return;
  initialized = true;
  let prev = getIsOnline();
  isOnline.subscribe((online) => {
    if (online && !prev) void linkAndSyncAll();
    prev = online;
  });
  // The transition alone is not enough: the app is often relaunched or
  // foregrounded when connectivity is already back — the store never
  // flips, and a trip's offline reading sat unpushed until the user
  // happened to open the book. Converge on every foreground instead;
  // the cooldown keeps it cheap.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void linkAndSyncAll();
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
    let failures = 0;
    try {
      // Before the empty-shelf return: the reading-time ledger outlives
      // its books (read-then-deleted still counts toward the streak).
      void pushLedger();
      const books = await listLocalBooks();
      if (books.length === 0) return;
      const links = await getLocalBookLinks();
      const unlinked = books.filter((b) => !links[b.id]);
      if (unlinked.length > 0) {
        // Isolated: a failed lookup must not stop already-linked books
        // below from pushing their reading state.
        try {
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
          void refreshLinkedBookIds();
        } catch (err) {
          console.warn("readingSync: digest lookup failed", err);
          failures += 1;
        }
      }
      // Sequentially — local shelves are small, and a burst of parallel
      // merges would stampede NAS-class servers for no gain. Per-book
      // isolation: one bad book must not strand the rest of the shelf.
      let synced = 0;
      for (const book of books) {
        if (!links[book.id]) continue;
        try {
          await syncLocalBook(book.id);
          synced += 1;
        } catch (err) {
          console.warn(`readingSync: sync failed for ${book.id}`, err);
          failures += 1;
        }
      }
      if (synced > 0) readingSyncStamp.update((n) => n + 1);
    } catch (err) {
      console.warn("readingSync: full sync failed", err);
      failures += 1;
    } finally {
      if (failures === 0) {
        lastFullSyncAt = Date.now();
      } else {
        // iOS reports connectivity back seconds before DNS actually works
        // (airplane mode off), so the first pass after a reconnect often
        // fails wholesale. Arming the cooldown then would swallow the real
        // retry — leave it unarmed and try again shortly instead. The
        // retry self-stops while unreachable (canSync gates on isOnline).
        scheduleRetry();
      }
      fullSyncInFlight = null;
    }
  })();
  return fullSyncInFlight;
}

const RETRY_DELAY_MS = 10_000;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleRetry(): void {
  if (retryTimer) return;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    void linkAndSyncAll();
  }, RETRY_DELAY_MS);
}

/** Post-import hook: try to link one book and sync it. True = linked. */
export async function linkAndSyncBook(entry: LocalBookEntry): Promise<boolean> {
  if (!canSync()) return false;
  try {
    if ((await resolveLink(entry.id)) === null) return false;
    await syncLocalBook(entry.id);
    return true;
  } catch (err) {
    console.warn("readingSync: link failed", err);
    return false;
  }
}

/** The book's server id: the stored link, or a fresh by-digest resolution
 *  (stored when found). Null = no accessible match on the server. */
async function resolveLink(localBookId: string): Promise<string | null> {
  const links = await getLocalBookLinks();
  if (links[localBookId]) return links[localBookId];
  const entry = await getLocalBook(localBookId);
  if (!entry) return null;
  const { matches } = await booksApi.lookupByDigest([entry.digest]);
  const match = matches[entry.digest];
  if (!match) return null;
  await setLocalBookLink(localBookId, match.id);
  void refreshLinkedBookIds();
  return match.id;
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

/** Throws on transport-level failure — a caller must be able to tell "the
 *  push landed" from "the network wasn't really there yet" (iOS reports
 *  connectivity seconds before DNS works after airplane mode). Swallowed
 *  failures here once armed the full-pass cooldown and left a trip's
 *  reading unpushed until the user happened to open the book. */
async function doSync(localBookId: string): Promise<void> {
  if (!canSync()) return;
  // Unlinked books get a by-digest attempt here, so opening a book is
  // always enough to (re)establish its link — no waiting for a full
  // pass after the matching server book (re)appears. A lookup failure
  // propagates: it means the server wasn't reachable.
  const serverBookId = await resolveLink(localBookId);
  if (!serverBookId) return;

  const progress = await readLocalProgress(localBookId);
  const highlights = await readLocalHighlightRecords(localBookId);
  const interaction = await readLocalInteraction(localBookId);
  const body = {
    progress: progress && progress.cfi ? toSyncProgress(progress) : null,
    highlights,
    // Only a device-edited status group (stamp present) is pushed; the
    // response snapshot still folds web edits back either way.
    interaction: interaction?.status_updated_at
      ? ({
          reading_status: interaction.reading_status,
          started_at: interaction.started_at,
          finished_at: interaction.finished_at,
          status_updated_at: interaction.status_updated_at,
        } satisfies SyncInteractionIn)
      : null,
  };

  let response: BookSyncResponse;
  try {
    response = await booksApi.syncReadingState(serverBookId, body);
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status !== 404 && status !== 403) {
      throw err;
    }
    // The linked server book is gone or access was revoked. Unlink, then
    // re-resolve by digest right away — a deleted-and-re-uploaded book
    // gets a new id, and this heals it in the same call.
    await clearLocalBookLink(localBookId);
    void refreshLinkedBookIds();
    const freshId = await resolveLink(localBookId);
    if (!freshId || freshId === serverBookId) return;
    response = await booksApi.syncReadingState(freshId, body);
  }

  await applyHighlights(localBookId, response);
  await applyProgress(localBookId, response);
  await applyInteraction(localBookId, response);
  await backfillEntryMeta(localBookId, serverBookId);
}

/** Entries imported before progress metadata existed measure progress with
 *  the uniform-weights fallback — a different ruler than the server's, so
 *  the same position reads as a different percentage depending on the
 *  entry (69% vs 86% on a real book). Every sync route passes through
 *  here, so one pass upgrades the entry no matter which entry point the
 *  book is opened from. Only real server values are stamped — a pending
 *  extraction must stay "unknown" so the next sync retries. */
async function backfillEntryMeta(
  localBookId: string,
  serverBookId: string,
): Promise<void> {
  try {
    const entry = await getLocalBook(localBookId);
    if (
      !entry ||
      (entry.sectionWeights !== undefined && entry.isImageBook !== undefined)
    ) {
      return;
    }
    const book = await booksApi.get(serverBookId);
    const meta: { isImageBook?: boolean; sectionWeights?: number[] } = {};
    if (
      entry.isImageBook === undefined &&
      typeof book.is_image_book === "boolean"
    ) {
      meta.isImageBook = book.is_image_book;
    }
    if (
      entry.sectionWeights === undefined &&
      Array.isArray(book.section_weights) &&
      book.section_weights.length > 0
    ) {
      meta.sectionWeights = book.section_weights;
    }
    if (Object.keys(meta).length > 0) {
      await updateLocalBookMeta(localBookId, meta);
    }
  } catch (err) {
    console.warn("readingSync: entry meta backfill failed", err);
  }
}

async function applyInteraction(
  localBookId: string,
  response: BookSyncResponse,
): Promise<void> {
  const remote = response.interaction;
  if (!remote?.status_updated_at) return;
  const fresh = await readLocalInteraction(localBookId);
  // Strictly newer only: an in-flight local edit (stamp past the echo)
  // must survive to be pushed next time. Ties are our own echo anyway.
  if (
    fresh?.status_updated_at &&
    Date.parse(fresh.status_updated_at) >= Date.parse(remote.status_updated_at)
  ) {
    return;
  }
  const record: LocalInteractionRecord = {
    reading_status: remote.reading_status,
    started_at: remote.started_at,
    finished_at: remote.finished_at,
    status_updated_at: remote.status_updated_at,
  };
  await writeLocalInteraction(localBookId, record);
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
