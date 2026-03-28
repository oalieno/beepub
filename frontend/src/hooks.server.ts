import { redirect, type Handle } from "@sveltejs/kit";
import { env } from "$env/dynamic/private";
import { building } from "$app/environment";

const BACKEND_URL = env.BACKEND_URL || "http://backend:8000";

export const handle: Handle = async ({ event, resolve }) => {
  // Skip auth during static build (adapter-static fallback page generation)
  if (building) {
    return resolve(event);
  }

  const token = event.cookies.get("token") ?? null;
  event.locals.token = token;
  event.locals.user = null;

  if (token) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        event.locals.user = await res.json();
      } else if (res.status === 401 || res.status === 403) {
        event.cookies.delete("token", { path: "/" });
        event.locals.token = null;
      }
    } catch {
      // Keep existing token on transient backend/network errors.
      // We only clear cookie when backend explicitly says the token is invalid.
    }
  }

  const path = event.url.pathname;

  // Redirect unauthenticated users to login (except login and setup pages)
  if (!event.locals.token && path !== "/login" && path !== "/setup") {
    throw redirect(302, "/login");
  }

  // Redirect authenticated users away from login page
  if (event.locals.user && path === "/login") {
    throw redirect(302, "/");
  }

  // Admin pages require admin role
  if (path.startsWith("/admin") && event.locals.user?.role !== "admin") {
    throw redirect(302, "/");
  }

  return resolve(event);
};
