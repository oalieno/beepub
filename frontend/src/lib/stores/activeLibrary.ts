import { derived, writable } from "svelte/store";
import { browser } from "$app/environment";

// Calibre-style "active library": the 書庫 nav entry jumps straight to the
// last-visited library; the cards page one level up is the switcher.
// "all" = the all-books pseudo-library, "device" = the local shelf.
export type ActiveLibrary = "all" | "device" | (string & {});

const STORAGE_KEY = "active-library";

function getInitial(): ActiveLibrary {
  if (!browser) return "all";
  try {
    return localStorage.getItem(STORAGE_KEY) || "all";
  } catch {
    return "all";
  }
}

export const activeLibrary = writable<ActiveLibrary>(getInitial());

export function setActiveLibrary(value: ActiveLibrary) {
  activeLibrary.set(value);
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Private browsing — the in-memory store still works for this session.
  }
}

export const activeLibraryHref = derived(activeLibrary, (v) =>
  v === "device" ? "/local" : `/libraries/${v}`,
);
