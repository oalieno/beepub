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
import {
  addTransfer,
  removeTransfer,
  updateTransfer,
} from "$lib/stores/transfers";

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

interface Job extends DownloadRequest {
  /** Its row in the transfer panel, where the outcome is reported. */
  transferId: string;
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
 *  already on their way are skipped; returns how many were queued. Each
 *  gets a row in the transfer panel, which reports how it went. */
export function enqueueDownloads(books: DownloadRequest[]): number {
  const linked = get(linkedServerBookIds);
  const busy = get(store);
  const seen = new Set<string>();
  const fresh = books.filter((b) => {
    if (linked.has(b.bookId) || busy.has(b.bookId) || seen.has(b.bookId))
      return false;
    seen.add(b.bookId);
    return true;
  });
  for (const b of fresh) {
    const transferId = addTransfer({
      kind: "download",
      title: b.title,
      href: `/books/${b.bookId}`,
    });
    queue.push({ ...b, transferId });
    setState(b.bookId, { state: "queued", progress: null });
  }
  if (fresh.length > 0) void pump();
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
      removeTransfer(job.transferId);
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
      updateTransfer(job.transferId, { status: "running", progress: 0 });
      try {
        const outcome = await fetchToLibrary(job);
        updateTransfer(job.transferId, { status: outcome, progress: null });
      } catch (e) {
        const { bookId, title, known } = job;
        const transferId = job.transferId;
        updateTransfer(transferId, {
          status: "failed",
          progress: null,
          error: (e as Error).message,
          retry: () => {
            removeTransfer(transferId);
            enqueueDownloads([{ bookId, title, known }]);
          },
        });
      }
      setState(job.bookId, null);
    }
  } finally {
    running = false;
  }
}

async function fetchToLibrary(job: Job): Promise<"done" | "duplicate"> {
  const [{ downloadEpubToLibrary }, { DuplicateBookError }] = await Promise.all(
    [
      import("$lib/services/epubDownload"),
      import("$lib/services/localLibrary"),
    ],
  );
  try {
    const entry = await downloadEpubToLibrary({
      url: fileUrl(job.bookId),
      headers: getAuthHeader(),
      title: job.title,
      // The server's name for the book, not the one inside the file.
      known: { ...job.known, title: job.title },
      onProgress: (pct) => {
        setState(job.bookId, { state: "downloading", progress: pct });
        updateTransfer(job.transferId, { progress: pct });
      },
    });
    // Same bytes as the server file — the digest link is guaranteed, and
    // syncing starts right away.
    void import("$lib/services/readingSync").then(({ linkAndSyncBook }) =>
      linkAndSyncBook(entry),
    );
    return "done";
  } catch (e) {
    if (!(e instanceof DuplicateBookError)) throw e;
    return "duplicate";
  } finally {
    await refreshLinkedBookIds();
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
