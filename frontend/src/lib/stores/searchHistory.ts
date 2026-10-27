import { get } from "svelte/store";
import { browser } from "$app/environment";
import { authStore } from "$lib/stores/auth";
import { isLocalMode } from "$lib/api/client";

/** Recent searches of the global search (⌘K): one list per account on
 *  this device, newest first. Logging out leaves it in place. */

const MAX_ENTRIES = 10;

function storageKey(): string {
  const id = get(authStore).user?.id;
  if (isLocalMode() || !id) return "search-history:local";
  return `search-history:${id}`;
}

function write(list: string[]): void {
  if (!browser) return;
  try {
    localStorage.setItem(storageKey(), JSON.stringify(list));
  } catch {
    // Private browsing or quota exceeded — silently ignore
  }
}

export function getHistory(): string[] {
  if (!browser) return [];
  try {
    const raw = localStorage.getItem(storageKey());
    if (!raw) return [];
    const list = JSON.parse(raw);
    return Array.isArray(list)
      ? list.filter((q): q is string => typeof q === "string")
      : [];
  } catch {
    return [];
  }
}

const same = (a: string, b: string) =>
  a.trim().toLowerCase() === b.trim().toLowerCase();

/** Put `q` at the front; a repeat moves there with its latest spelling. */
export function recordSearch(q: string): string[] {
  const term = q.trim();
  if (!term) return getHistory();
  const list = [term, ...getHistory().filter((h) => !same(h, term))].slice(
    0,
    MAX_ENTRIES,
  );
  write(list);
  return list;
}

export function removeSearch(q: string): string[] {
  const list = getHistory().filter((h) => !same(h, q));
  write(list);
  return list;
}

export function clearHistory(): string[] {
  write([]);
  return [];
}
