import { browser } from "$app/environment";
import { getServerUrl, isLocalMode } from "$lib/api/client";
import type { LayoutLoad } from "./$types";

const isCapacitor = import.meta.env.VITE_CAPACITOR === "true";

// Capacitor build: disable SSR (all rendering is client-side)
export const ssr = !isCapacitor;
export const prerender = false;

export const load: LayoutLoad = async ({ data }) => {
  // SSR (web) build: data comes from +layout.server.ts
  if (!isCapacitor && data?.user !== undefined) return { user: data.user };

  // SPA build (Capacitor): fetch user client-side
  if (browser) {
    // Local mode makes zero server traffic — the dormant session (if
    // any) stays untouched until the user switches back.
    if (isLocalMode()) return { user: null };
    // (Before the login is looked for: the system may have cleared the
    // web view's storage since the app was last open.)
    const { restoreTokens } = await import("$lib/auth/tokens");
    await restoreTokens();
    const token = localStorage.getItem("token");
    if (!token) return { user: null };
    try {
      const serverUrl = getServerUrl();
      const me = (bearer: string) =>
        fetch(`${serverUrl}/api/auth/me`, {
          headers: { Authorization: `Bearer ${bearer}` },
        });
      let res = await me(token);
      if (res.status === 401) {
        // The access token has run out since the app was last open; the
        // refresh token, which lasts far longer, gets a new one. Only
        // when that is refused too is the person signed out.
        const { refreshAccessToken } = await import("$lib/api/client");
        const fresh = (await refreshAccessToken())
          ? localStorage.getItem("token")
          : null;
        if (fresh) res = await me(fresh);
      }
      if (res.ok) return { user: await res.json() };
    } catch {
      // Server unreachable — try cached user for offline mode
      try {
        const { getCachedUser } = await import("$lib/stores/auth");
        const cached = await getCachedUser();
        if (cached) return { user: cached };
      } catch {
        // ignore
      }
    }
    return { user: null };
  }

  return { user: null };
};
