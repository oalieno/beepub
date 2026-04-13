import { writable } from "svelte/store";
import { browser } from "$app/environment";

const STORAGE_KEY = "sidebar-collapsed";

function getInitial(): boolean {
  if (!browser) return false;
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export const sidebarCollapsed = writable<boolean>(getInitial());

if (browser) {
  sidebarCollapsed.subscribe((v) => {
    try {
      localStorage.setItem(STORAGE_KEY, String(v));
    } catch {
      // Private browsing or quota exceeded — silently ignore
    }
  });
}

export function toggleSidebar() {
  sidebarCollapsed.update((v) => !v);
}
