import { browser } from "$app/environment";
import { getServerUrl } from "$lib/api/client";
import type { LayoutLoad } from "./$types";

// Capacitor build: disable SSR (all rendering is client-side)
export const ssr = !(import.meta.env.VITE_CAPACITOR === "true");
export const prerender = false;

export const load: LayoutLoad = async ({ data }) => {
  // SSR build: data comes from +layout.server.ts
  if (data?.user !== undefined) return { user: data.user };

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
      // Server unreachable
    }
    return { user: null };
  }

  return { user: null };
};
