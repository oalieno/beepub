import type { HandleClientError } from "@sveltejs/kit";

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
