import { derived, writable } from "svelte/store";
import { browser } from "$app/environment";

// Calibre-style "active library": the 書庫 nav entry jumps straight to the
// last-visited library; the cards page one level up is the switcher.
// "all" = the all-books pseudo-library. The device shelf is the other
// library (local mode), never a server library to jump into.
export type ActiveLibrary = "all" | (string & {});

const STORAGE_KEY = "active-library";

function getInitial(): ActiveLibrary {
  if (!browser) return "all";
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    // "device" was the local shelf's card among the server libraries,
    // before the two libraries split — it has no server page any more.
    return stored && stored !== "device" ? stored : "all";
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

export const activeLibraryHref = derived(
  activeLibrary,
  (v) => `/libraries/${v}`,
);
