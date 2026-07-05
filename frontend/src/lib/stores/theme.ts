import { writable, get } from "svelte/store";
import { browser } from "$app/environment";

export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "theme";

function getInitial(): ThemePreference {
  if (!browser) return "system";
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark" || saved === "system") {
      return saved;
    }
  } catch {
    // Private browsing — fall through to default
  }
  return "system";
}

export const themePreference = writable<ThemePreference>(getInitial());

export function resolveDark(pref: ThemePreference): boolean {
  if (pref === "system") {
    return browser
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
  }
  return pref === "dark";
}

function apply(pref: ThemePreference) {
  document.documentElement.classList.toggle("dark", resolveDark(pref));
}

if (browser) {
  themePreference.subscribe((pref) => {
    try {
      localStorage.setItem(STORAGE_KEY, pref);
    } catch {
      // Private browsing or quota exceeded — silently ignore
    }
    apply(pref);
  });

  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      apply(get(themePreference));
    });
}

export function setThemePreference(pref: ThemePreference) {
  themePreference.set(pref);
}
