import { redirect, type Handle, type RequestEvent } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";
import { env } from "$env/dynamic/private";
import { building } from "$app/environment";
import { paraglideMiddleware } from "$lib/paraglide/server.js";
import {
  cookieName,
  defineCustomServerStrategy,
} from "$lib/paraglide/runtime.js";
import {
  BROWSER_LOCALE_STRATEGY,
  localeFromAcceptLanguage,
} from "$lib/i18n/browserLocale";

const BACKEND_URL = env.BACKEND_URL || "http://backend:8000";

// A visitor who hasn't picked a language gets the browser's. Paraglide
// asks custom strategies before the cookie, so a chosen language is
// stepped aside for here.
defineCustomServerStrategy(BROWSER_LOCALE_STRATEGY, {
  getLocale: (request) => {
    const cookies = request?.headers.get("cookie") ?? "";
    if (cookies.split(";").some((c) => c.trim().startsWith(`${cookieName}=`)))
      return undefined;
    return localeFromAcceptLanguage(
      request?.headers.get("accept-language") ?? null,
    );
  },
});

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

// The refresh cookie is sent with every request — it has to reach this
// hook, which is what renews an access token that has run out. Older
// versions scoped it to /api/auth; that one is cleared when found dead.
const REFRESH_COOKIE_PATH = "/";
const LEGACY_REFRESH_COOKIE_PATH = "/api/auth";
// As long as a browser keeps a cookie; set again on every renewal.
const REFRESH_MAX_AGE = 400 * 24 * 60 * 60;

async function tryRefresh(
  refreshToken: string,
): Promise<{ accessToken: string; maxAge: number } | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `refresh_token=${refreshToken}` },
    });
    if (!res.ok) return null;
    const body = (await res.json()) as {
      access_token?: string;
      expires_in?: number;
    };
    if (!body.access_token) return null;
    return {
      accessToken: body.access_token,
      maxAge: body.expires_in ?? 30 * 60,
    };
  } catch {
    return null;
  }
}

/** Whether the person reached the site over https (a TLS proxy in front
 *  says so in X-Forwarded-Proto). Over plain http a browser drops a
 *  cookie marked Secure, so the flag follows the scheme — as the backend's
 *  own cookies do. */
function overHttps(event: RequestEvent): boolean {
  const forwarded = event.request.headers.get("x-forwarded-proto");
  const scheme = forwarded
    ? forwarded.split(",")[0].trim()
    : event.url.protocol.replace(":", "");
  return scheme === "https";
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

  const signedOut = () => {
    event.cookies.delete("token", { path: "/" });
    event.cookies.delete("refresh_token", { path: REFRESH_COOKIE_PATH });
    event.cookies.delete("refresh_token", { path: LEGACY_REFRESH_COOKIE_PATH });
    event.locals.token = null;
  };

  /** A new access token from the refresh token, its cookie set. The
   *  refresh cookie is set again too, so the browser keeps it longer. */
  const renew = async (): Promise<boolean> => {
    if (!refreshToken) return false;
    const refreshed = await tryRefresh(refreshToken);
    if (!refreshed) return false;
    token = refreshed.accessToken;
    event.locals.token = token;
    const cookie = {
      path: "/",
      httpOnly: true,
      secure: overHttps(event),
      sameSite: "lax" as const,
    };
    event.cookies.set("token", token, { ...cookie, maxAge: refreshed.maxAge });
    event.cookies.set("refresh_token", refreshToken, {
      ...cookie,
      path: REFRESH_COOKIE_PATH,
      maxAge: REFRESH_MAX_AGE,
    });
    return true;
  };

  try {
    // No access cookie (it ran out and the browser dropped it), or one
    // the backend refuses: renew it before sending anyone to /login.
    let res = token ? await fetchMe(token) : null;
    if ((!res || res.status === 401 || res.status === 403) && (await renew())) {
      res = await fetchMe(token!);
    }
    if (res?.ok) {
      event.locals.user = await res.json();
    } else if (!res || res.status === 401 || res.status === 403) {
      // The backend said no (or there was nothing to ask with).
      signedOut();
    }
  } catch {
    // Keep the cookies on a transient backend/network error: they are
    // cleared only when the backend says the login is no longer good.
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
