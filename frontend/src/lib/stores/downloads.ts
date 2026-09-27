/**
 * Server books on their way into the device's local library — one queue
 * for the whole app, one download at a time, in the order they were
 * asked for (a series arrives volume 1 first).
 *
 * The state lives here, not in the page that asked: a book page is
 * reused when the reader moves to the next volume and destroyed when
 * they leave, while the download itself runs on. Everything is keyed by
 * server book id, so each page reads only its own book's state.
 *
 * "Download to phone" (the share sheet) is not queued — the reader is
 * waiting on the sheet — but shows up here while it fetches, so the
 * book's button reads the same whichever way the bytes are travelling.
 */
import { get, writable, type Readable } from "svelte/store";

import { apiBase, getAuthHeader } from "$lib/api/client";
import * as m from "$lib/paraglide/messages.js";
import {
  linkedServerBookIds,
  refreshLinkedBookIds,
} from "$lib/stores/linkedBooks";
import { toastStore } from "$lib/stores/toast";

export interface DownloadRequest {
  bookId: string;
  title: string;
  known?: {
    isImageBook?: boolean | null;
    sectionWeights?: number[] | null;
  };
}

export interface DownloadState {
  state: "queued" | "downloading" | "sharing";
  /** 0..100; null while the size is unknown. */
  progress: number | null;
}

/** A set of books asked for together; it reports once, when it empties. */
interface Batch {
  /** Names the set in the closing toast (a series). */
  label: string;
  size: number;
  pending: number;
  done: number;
  failed: DownloadRequest[];
}

interface Job extends DownloadRequest {
  batch: Batch;
}

const store = writable<ReadonlyMap<string, DownloadState>>(new Map());
let queue: Job[] = [];
let running = false;

/** Books queued, downloading or sharing, by server book id. */
export const downloads: Readable<ReadonlyMap<string, DownloadState>> = {
  subscribe: store.subscribe,
};

function setState(bookId: string, state: DownloadState | null) {
  store.update((map) => {
    const next = new Map(map);
    if (state) next.set(bookId, state);
    else next.delete(bookId);
    return next;
  });
}

const fileUrl = (bookId: string) => `${apiBase()}/books/${bookId}/file`;

/** Queue books for the local library. Books already on the device or
 *  already on their way are skipped; returns how many were queued. */
export function enqueueDownloads(
  books: DownloadRequest[],
  opts: { label?: string } = {},
): number {
  const linked = get(linkedServerBookIds);
  const busy = get(store);
  const seen = new Set<string>();
  const fresh = books.filter((b) => {
    if (linked.has(b.bookId) || busy.has(b.bookId) || seen.has(b.bookId))
      return false;
    seen.add(b.bookId);
    return true;
  });
  if (fresh.length === 0) return 0;
  const batch: Batch = {
    label: opts.label ?? "",
    size: fresh.length,
    pending: fresh.length,
    done: 0,
    failed: [],
  };
  for (const b of fresh) {
    queue.push({ ...b, batch });
    setState(b.bookId, { state: "queued", progress: null });
  }
  void pump();
  return fresh.length;
}

/** Take queued books back out. The one already downloading finishes —
 *  the transfer can't be stopped halfway. */
export function cancelDownloads(bookIds: Iterable<string>): void {
  const ids = new Set(bookIds);
  const keep: Job[] = [];
  for (const job of queue) {
    if (ids.has(job.bookId)) {
      setState(job.bookId, null);
      settle(job, null);
    } else {
      keep.push(job);
    }
  }
  queue = keep;
}

async function pump(): Promise<void> {
  if (running) return;
  running = true;
  try {
    let job: Job | undefined;
    while ((job = queue.shift())) {
      setState(job.bookId, { state: "downloading", progress: 0 });
      let outcome: "done" | Error;
      try {
        await fetchToLibrary(job);
        outcome = "done";
      } catch (e) {
        outcome = e as Error;
      }
      setState(job.bookId, null);
      settle(job, outcome);
    }
  } finally {
    running = false;
  }
}

async function fetchToLibrary(job: Job): Promise<void> {
  const [{ downloadEpubToLibrary }, { DuplicateBookError }] = await Promise.all(
    [
      import("$lib/services/epubDownload"),
      import("$lib/services/localLibrary"),
    ],
  );
  // A lone book reports as it lands; a batch once, when it empties.
  const single = job.batch.size === 1;
  try {
    const entry = await downloadEpubToLibrary({
      url: fileUrl(job.bookId),
      headers: getAuthHeader(),
      title: job.title,
      known: job.known,
      onProgress: (pct) =>
        setState(job.bookId, { state: "downloading", progress: pct }),
    });
    if (single) toastStore.success(m.download_done({ title: entry.title }));
    // Same bytes as the server file — the digest link is guaranteed, and
    // syncing starts right away.
    void import("$lib/services/readingSync").then(({ linkAndSyncBook }) =>
      linkAndSyncBook(entry),
    );
  } catch (e) {
    if (!(e instanceof DuplicateBookError)) throw e;
    if (single)
      toastStore.info(m.local_import_duplicate({ title: e.existing.title }));
  } finally {
    await refreshLinkedBookIds();
  }
}

/** One job left its batch: counted (done / failed) or cancelled (null). */
function settle(job: Job, outcome: "done" | Error | null) {
  const batch = job.batch;
  batch.pending--;
  if (outcome === "done") batch.done++;
  else if (outcome) batch.failed.push(job);
  if (batch.pending > 0) return;

  if (batch.size === 1) {
    if (outcome instanceof Error)
      toastStore.error(
        m.book_download_failed({ error: String(outcome.message) }),
      );
    return;
  }
  const label = batch.label;
  if (batch.failed.length > 0) {
    const retry = batch.failed.map(({ bookId, title, known }) => ({
      bookId,
      title,
      known,
    }));
    toastStore.error(
      m.download_batch_failed({ count: String(batch.failed.length) }),
      {
        action: {
          label: m.common_retry(),
          onclick: () => enqueueDownloads(retry, { label }),
        },
      },
    );
  } else if (batch.done > 0) {
    toastStore.success(
      m.download_batch_done({ title: label, count: String(batch.done) }),
    );
  }
}

/** "Download to phone": straight to the OS share sheet (save to Files,
 *  AirDrop, open in another reader). A local copy, when there is one,
 *  skips the network, invisibly. */
export async function shareBook(req: DownloadRequest): Promise<void> {
  if (get(store).has(req.bookId)) return;
  try {
    const { getLocalBookLinks, shareLocalBookFile } =
      await import("$lib/services/localLibrary");
    const links = await getLocalBookLinks();
    const localId = Object.keys(links).find((id) => links[id] === req.bookId);
    if (localId) {
      await shareLocalBookFile(localId);
      return;
    }
    setState(req.bookId, { state: "sharing", progress: 0 });
    const { downloadEpubToDevice } = await import("$lib/services/epubDownload");
    await downloadEpubToDevice({
      url: fileUrl(req.bookId),
      headers: getAuthHeader(),
      title: req.title,
      onProgress: (pct) =>
        setState(req.bookId, { state: "sharing", progress: pct }),
    });
  } catch (e) {
    // Dismissing the share sheet also rejects — that is not an error.
    const msg = (e as Error).message ?? "";
    if (!/cancel/i.test(msg)) toastStore.error(msg || m.local_export_failed());
  } finally {
    setState(req.bookId, null);
  }
}
