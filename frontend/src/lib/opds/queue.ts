/**
 * Books fetched from catalogs — onto the device (a device catalog) or into
 * a server library (a server catalog). One queue for the app, one book at
 * a time (don't stampede NAS-class servers), outliving the catalog page:
 * leaving mid-queue and coming back finds each book's state, and the
 * transfer panel reports every outcome.
 */
import { writable, type Readable } from "svelte/store";

import * as m from "$lib/paraglide/messages.js";
import {
  addTransfer,
  removeTransfer,
  updateTransfer,
} from "$lib/stores/transfers";

import { OpdsError } from "./errors";
import type { OpdsBookEntry } from "./parse";

export interface CatalogItemState {
  status: "queued" | "downloading" | "imported" | "duplicate" | "error";
  pct: number | null;
  /** The book it became or already was. */
  href?: string;
}

interface Job {
  key: string;
  side: "device" | "server";
  catalogId: string;
  entry: OpdsBookEntry;
  /** Server: the library it goes into. */
  libraryId?: string;
  /** Device: the catalog's sign-in, captured when asked. */
  auth?: { username?: string | null; password?: string | null };
  transferId: string;
}

const states = writable<ReadonlyMap<string, CatalogItemState>>(new Map());
let queue: Job[] = [];
let running = false;

/** Per-book state, keyed by catalogItemKey. */
export const catalogItemStates: Readable<
  ReadonlyMap<string, CatalogItemState>
> = { subscribe: states.subscribe };

export function catalogItemKey(catalogId: string, entryKey: string): string {
  return `${catalogId}|${entryKey}`;
}

function setState(key: string, state: CatalogItemState | null) {
  states.update((map) => {
    const next = new Map(map);
    if (state) next.set(key, state);
    else next.delete(key);
    return next;
  });
}

let current: ReadonlyMap<string, CatalogItemState> = new Map();
states.subscribe((map) => (current = map));

/** Ask for a book. A failed one can be asked for again; anything queued,
 *  running or settled is left alone. */
export function enqueueCatalogBook(req: Omit<Job, "key" | "transferId">): void {
  const key = catalogItemKey(req.catalogId, req.entry.key);
  const state = current.get(key)?.status;
  if (state && state !== "error") return;
  const transferId = addTransfer({
    kind: req.side === "server" ? "import" : "download",
    title: req.entry.title,
  });
  setState(key, { status: "queued", pct: null });
  queue.push({ ...req, key, transferId });
  void pump();
}

async function pump(): Promise<void> {
  if (running) return;
  running = true;
  try {
    let job: Job | undefined;
    while ((job = queue.shift())) await run(job);
  } finally {
    running = false;
  }
}

async function run(job: Job): Promise<void> {
  setState(job.key, { status: "downloading", pct: null });
  updateTransfer(job.transferId, { status: "running" });
  try {
    const { status, href } =
      job.side === "server" ? await importToServer(job) : await download(job);
    setState(job.key, { status, pct: null, href });
    updateTransfer(job.transferId, {
      status: status === "imported" ? "done" : "duplicate",
      progress: null,
      href,
    });
  } catch (err) {
    setState(job.key, { status: "error", pct: null });
    const { key: _key, transferId, ...req } = job;
    updateTransfer(transferId, {
      status: "failed",
      progress: null,
      error: failure(err),
      retry: () => {
        removeTransfer(transferId);
        enqueueCatalogBook(req);
      },
    });
  }
}

async function importToServer(
  job: Job,
): Promise<{ status: "imported" | "duplicate"; href: string }> {
  const { importToServer } = await import("./server");
  const { status, book } = await importToServer(
    job.catalogId,
    job.entry,
    job.libraryId!,
  );
  return { status, href: `/books/${book.id}` };
}

async function download(
  job: Job,
): Promise<{ status: "imported" | "duplicate"; href: string }> {
  const { downloadAndImport } = await import("./download");
  const { DuplicateBookError } = await import("$lib/services/localLibrary");
  try {
    const entry = await downloadAndImport(job.entry, job.auth ?? {}, (pct) => {
      setState(job.key, { status: "downloading", pct });
      updateTransfer(job.transferId, { progress: pct });
    });
    return { status: "imported", href: `/local/${entry.id}` };
  } catch (err) {
    if (!(err instanceof DuplicateBookError)) throw err;
    return { status: "duplicate", href: `/local/${err.existing.id}` };
  }
}

/** A reason worth showing; empty leaves the row at a plain "failed". */
function failure(err: unknown): string {
  if (err instanceof OpdsError)
    return err.kind === "blocked" ? m.catalogs_blocked_error() : "";
  if ((err as Error)?.name === "InvalidEpubError")
    return m.local_import_invalid();
  return (err as Error)?.message ?? "";
}
