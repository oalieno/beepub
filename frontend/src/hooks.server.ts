import { redirect, type Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";
import { env } from "$env/dynamic/private";
import { building } from "$app/environment";
import { paraglideMiddleware } from "$lib/paraglide/server.js";

const BACKEND_URL = env.BACKEND_URL || "http://backend:8000";

const i18nHandle: Handle = ({ event, resolve }) =>
  paraglideMiddleware(
    event.request,
    ({ request: localizedRequest, locale }) => {
      event.request = localizedRequest;
      return resolve(event, {
        transformPageChunk: ({ html }) => {
          return html.replace("%lang%", locale);
        },
      });
    },
  );

const REFRESH_COOKIE_PATH = "/api/auth";
const ACCESS_MAX_AGE = 30 * 60; // must match backend access_token_expire_minutes

async function tryRefresh(
  refreshToken: string,
): Promise<{ accessToken: string; setCookie: string | null } | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `refresh_token=${refreshToken}` },
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { access_token?: string };
    if (!body.access_token) return null;
    return {
      accessToken: body.access_token,
      setCookie: res.headers.get("set-cookie"),
    };
  } catch {
    return null;
  }
}

const authHandle: Handle = async ({ event, resolve }) => {
  // Skip auth during static build (adapter-static fallback page generation)
  if (building) {
    return resolve(event);
  }

  let token = event.cookies.get("token") ?? null;
  const refreshToken = event.cookies.get("refresh_token") ?? null;
  event.locals.token = token;
  event.locals.user = null;

  const fetchMe = async (bearer: string) =>
    fetch(`${BACKEND_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${bearer}` },
    });

  if (token) {
    try {
      let res = await fetchMe(token);
      if ((res.status === 401 || res.status === 403) && refreshToken) {
        // Access token rejected — try refreshing it transparently before
        // bouncing the user to /login.
        const refreshed = await tryRefresh(refreshToken);
        if (refreshed) {
          token = refreshed.accessToken;
          event.locals.token = token;
          event.cookies.set("token", token, {
            path: "/",
            httpOnly: true,
            secure: true,
            sameSite: "lax",
            maxAge: ACCESS_MAX_AGE,
          });
          res = await fetchMe(token);
        }
      }
      if (res.ok) {
        event.locals.user = await res.json();
      } else if (res.status === 401 || res.status === 403) {
        event.cookies.delete("token", { path: "/" });
        event.cookies.delete("refresh_token", { path: REFRESH_COOKIE_PATH });
        event.locals.token = null;
      }
    } catch {
      // Keep existing token on transient backend/network errors.
      // We only clear cookie when backend explicitly says the token is invalid.
    }
  } else if (refreshToken) {
    // Access cookie missing (expired and pruned by browser) but refresh
    // cookie still valid — mint a new access token from refresh.
    const refreshed = await tryRefresh(refreshToken);
    if (refreshed) {
      token = refreshed.accessToken;
      event.locals.token = token;
      event.cookies.set("token", token, {
        path: "/",
        httpOnly: true,
        secure: true,
        sameSite: "lax",
        maxAge: ACCESS_MAX_AGE,
      });
      try {
        const res = await fetchMe(token);
        if (res.ok) {
          event.locals.user = await res.json();
        }
      } catch {
        // Network glitch — let the page render unauthenticated and let
        // the client retry on its own.
      }
    } else {
      event.cookies.delete("refresh_token", { path: REFRESH_COOKIE_PATH });
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

export const handle = sequence(i18nHandle, authHandle);
