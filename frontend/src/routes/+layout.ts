import { browser } from "$app/environment";
import { getServerUrl } from "$lib/api/client";
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
    const token = localStorage.getItem("token");
    if (!token) return { user: null };
    try {
      const serverUrl = getServerUrl();
      const res = await fetch(`${serverUrl}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
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
