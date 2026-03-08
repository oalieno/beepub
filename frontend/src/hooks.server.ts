import { redirect, type Handle } from "@sveltejs/kit";
import { env } from "$env/dynamic/private";

const BACKEND_URL = env.BACKEND_URL || "http://backend:8000";

export const handle: Handle = async ({ event, resolve }) => {
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

  // Redirect unauthenticated users to login (except the login page itself)
  const path = event.url.pathname;
  if (!event.locals.token && path !== "/login") {
    throw redirect(302, "/login");
  }

  return resolve(event);
};
