import { writable } from "svelte/store";

/** Global search overlay state. Lives in a store so pages outside the
 *  layout (e.g. the library browser's no-results bridge) can open the
 *  ⌘K overlay, optionally prefilled with a query. */
export const searchModalOpen = writable(false);
export const searchModalQuery = writable("");

export function openSearchModal(query = "") {
  searchModalQuery.set(query);
  searchModalOpen.set(true);
}
