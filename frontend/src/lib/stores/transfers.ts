/**
 * Work that takes a while and runs on its own — downloads to the device,
 * catalog imports, uploads — listed in one panel (TransferPanel) until
 * the reader closes it. Outcomes of these used to be toasts, which were
 * gone before anyone looked; a queue of them needs a place that stays.
 *
 * Producers add an item and update it as it runs; the panel only reads.
 */
import { derived, get, writable } from "svelte/store";

export type TransferKind = "download" | "import" | "upload";
export type TransferStatus =
  | "queued"
  | "running"
  | "done"
  | "duplicate"
  | "failed";

export interface Transfer {
  id: string;
  kind: TransferKind;
  title: string;
  status: TransferStatus;
  /** 0..100 while running, when the size is known. */
  progress: number | null;
  /** Where the result lives (the book). */
  href?: string;
  error?: string;
  /** Offered on a failed item. */
  retry?: () => void;
}

const items = writable<Transfer[]>([]);
/** Folded down to its summary line. */
export const transfersCollapsed = writable(false);

export const transfers = { subscribe: items.subscribe };

const SETTLED: TransferStatus[] = ["done", "duplicate", "failed"];

export const transferSummary = derived(items, (list) => {
  const active = list.filter((t) => !SETTLED.includes(t.status)).length;
  const failed = list.filter((t) => t.status === "failed").length;
  const running = list.find((t) => t.status === "running");
  return {
    total: list.length,
    active,
    settled: list.length - active,
    failed,
    /** The one in flight, for the summary's progress bar. */
    running: running ?? null,
  };
});

let seq = 0;

export function addTransfer(
  item: Omit<Transfer, "id" | "status" | "progress"> &
    Partial<Pick<Transfer, "status">>,
): string {
  const id = `t${++seq}`;
  // A new batch reopens a panel the reader folded away.
  if (get(items).every((t) => SETTLED.includes(t.status)))
    transfersCollapsed.set(false);
  items.update((list) => [
    ...list,
    { status: "queued", progress: null, ...item, id },
  ]);
  return id;
}

export function updateTransfer(
  id: string,
  patch: Partial<Omit<Transfer, "id">>,
): void {
  items.update((list) =>
    list.map((t) => (t.id === id ? { ...t, ...patch } : t)),
  );
}

export function removeTransfer(id: string): void {
  items.update((list) => list.filter((t) => t.id !== id));
}

/** Close the panel: settled items go; anything still running stays. */
export function clearSettledTransfers(): void {
  items.update((list) => list.filter((t) => !SETTLED.includes(t.status)));
}
