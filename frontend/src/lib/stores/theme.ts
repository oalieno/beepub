import { writable, get } from "svelte/store";
import { browser } from "$app/env";

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

// The browser's own bar (and the installed web app's title bar) follows
// the theme in use — which the reader may have set against the system's.
// (app.html holds the same two colours for the first paint.)
const BAR_COLOR = { light: "#b8860b", dark: "#171310" };

function apply(pref: ThemePreference) {
  const dark = resolveDark(pref);
  document.documentElement.classList.toggle("dark", dark);
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => {
    meta.setAttribute("content", dark ? BAR_COLOR.dark : BAR_COLOR.light);
  });
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
