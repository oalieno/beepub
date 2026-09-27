/**
 * The server library's view of the device: which server books have a
 * downloaded copy here (the "Downloaded" shelf), and taking one off.
 * Membership lives on the device — the digest link map — so the shelf
 * pages these ids through the server's book list itself.
 */
import { writable } from "svelte/store";

import { getIsOnline } from "$lib/services/network";
import {
  getLocalBookLinks,
  listLocalBooks,
  removeLocalBook,
} from "$lib/services/localLibrary";
import { refreshLinkedBookIds } from "$lib/stores/linkedBooks";

/** Server ids whose copy was removed this session — pages kept alive
 *  across navigation (the Downloaded shelf restored on back) drop them
 *  without refetching. */
export const removedDownloads = writable<ReadonlySet<string>>(new Set());

/** Server ids of the downloaded books, newest download first. */
export async function downloadedServerIds(): Promise<string[]> {
  const [links, entries] = await Promise.all([
    getLocalBookLinks(),
    listLocalBooks(),
  ]);
  return entries
    .filter((e) => links[e.id])
    .sort((a, b) => b.importedAt.localeCompare(a.importedAt))
    .map((e) => links[e.id]);
}

/** The copy's reading hasn't reached the server; removing it now would
 *  lose it. */
export class UnsyncedCopyError extends Error {
  constructor() {
    super("The downloaded copy has unsynced reading state");
    this.name = "UnsyncedCopyError";
  }
}

/** Delete a server book's downloaded copy. Its device records are pushed
 *  first — a highlight made offline lives only there until then. */
export async function removeDownload(serverBookId: string): Promise<void> {
  const links = await getLocalBookLinks();
  const localId = Object.keys(links).find((k) => links[k] === serverBookId);
  if (!localId) return;
  if (!getIsOnline()) throw new UnsyncedCopyError();
  const { pushLocalBook } = await import("$lib/services/readingSync");
  try {
    await pushLocalBook(localId);
  } catch {
    throw new UnsyncedCopyError();
  }
  await removeLocalBook(localId);
  await refreshLinkedBookIds();
  removedDownloads.update((s) => new Set([...s, serverBookId]));
}
