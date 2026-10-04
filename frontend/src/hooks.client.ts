import type { HandleClientError } from "@sveltejs/kit";
import { defineCustomClientStrategy } from "$lib/paraglide/runtime.js";
import {
  BROWSER_LOCALE_STRATEGY,
  localeFromLanguages,
} from "$lib/i18n/browserLocale";

// A visitor who hasn't picked a language gets the browser's. Not stored:
// the choice in the language menu is what sticks.
defineCustomClientStrategy(BROWSER_LOCALE_STRATEGY, {
  getLocale: () => localeFromLanguages(navigator.languages ?? []),
  setLocale: () => {},
});

export const handleError: HandleClientError = ({ error }) => {
  // iOS kills the service worker when a PWA is backgrounded.
  // When resuming, SvelteKit can't load JS modules → TypeError.
  // Force a full page reload to recover.
  if (
    error instanceof TypeError &&
    error.message?.includes("Importing a module script failed")
  ) {
    window.location.reload();
    return { message: "Reloading…" };
  }
};
