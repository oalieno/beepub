import * as m from "$lib/paraglide/messages.js";
import { errorMessage } from "./errors";
import {
  getIsOnline,
  reportServerReachable,
  reportServerUnreachable,
} from "$lib/services/network";

const SERVER_URL_KEY = "serverUrl";
const LOCAL_MODE_KEY = "localMode";

export function getServerUrl(): string {
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem(SERVER_URL_KEY);
    if (stored) return stored;
  }
  return import.meta.env.VITE_API_BASE || "";
}

export function setServerUrl(url: string): void {
  localStorage.setItem(SERVER_URL_KEY, url.replace(/\/$/, ""));
  // Connecting a server always exits serverless local mode.
  localStorage.removeItem(LOCAL_MODE_KEY);
}

export function hasServerUrl(): boolean {
  if (typeof window !== "undefined") {
    return !!localStorage.getItem(SERVER_URL_KEY);
  }
  return !!(import.meta.env.VITE_API_BASE as string);
}

/** Local (serverless) mode: the user chose to use the app without a
 *  server — on /setup or via the mode switcher (/mode). The flag alone
 *  decides: server credentials may lie dormant underneath, so switching
 *  back is free. Never set on web. */
export function isLocalMode(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(LOCAL_MODE_KEY) === "1";
}

export function setLocalMode(on: boolean): void {
  if (on) {
    localStorage.setItem(LOCAL_MODE_KEY, "1");
  } else {
    localStorage.removeItem(LOCAL_MODE_KEY);
  }
}

/** Explicit mode switch (native): a full page load, not SPA navigation —
 *  mode is deliberately read once per app lifetime across the tree. */
export function switchAppMode(mode: "server" | "local"): void {
  setLocalMode(mode === "local");
  window.location.replace("/");
}

export function apiBase(): string {
  return getServerUrl() + "/api";
}

/**
 * Cover image URL. Web uses nginx fast path (/covers/), native uses API.
 * Pass `version` (e.g. book.updated_at) to bust browser/CDN caches when
 * the cover is replaced.
 *
 * `size: "thumb"` is the small cover (480px wide, WebP) for where covers
 * are shown small and many — cards, rows, results: a fifth of the bytes.
 * A book that has no thumbnail yet answers with its full cover.
 */
export function coverUrl(
  bookId: string,
  version?: string | number | null,
  size: "full" | "thumb" = "full",
): string {
  const thumb = size === "thumb";
  const base = isNativePlatform()
    ? `${apiBase()}/books/${bookId}/cover`
    : thumb
      ? `/covers/thumb/${bookId}.jpg.webp`
      : `/covers/${bookId}.jpg`;
  const params = new URLSearchParams();
  if (thumb && isNativePlatform()) params.set("size", "thumb");
  if (version !== undefined && version !== null)
    params.set(
      "v",
      String(
        typeof version === "string" ? Date.parse(version) || version : version,
      ),
    );
  const query = params.toString();
  return query ? `${base}?${query}` : base;
}

function isNativePlatform(): boolean {
  if (typeof window === "undefined") return false;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Capacitor?.isNativePlatform?.() ?? false;
}

export function getAuthHeader(): Record<string, string> {
  if (typeof window !== "undefined") {
    // Only send Authorization header in native (Capacitor) mode.
    // Web mode relies on HttpOnly cookies; a stale Bearer token would
    // override the valid cookie (backend prioritises Bearer over cookie).
    if (!isNativePlatform()) return {};
    const token = localStorage.getItem("token");
    if (token) return { Authorization: `Bearer ${token}` };
  }
  return {};
}

// Dedupe parallel refreshes: if many in-flight calls 401 at once, only the
// first one talks to /auth/refresh; the others await the same promise.
let refreshInFlight: Promise<boolean> | null = null;

export async function refreshAccessToken(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const headers: Record<string, string> = {};
      if (isNativePlatform()) {
        const refresh = localStorage.getItem("refresh_token");
        if (!refresh) return false;
        headers["X-Refresh-Token"] = refresh;
      }
      const res = await fetch(`${apiBase()}/auth/refresh`, {
        method: "POST",
        headers,
        credentials: "include",
      });
      if (!res.ok) return false;
      if (isNativePlatform()) {
        const body = (await res.json()) as { access_token?: string };
        if (body.access_token) {
          localStorage.setItem("token", body.access_token);
        }
      }
      return true;
    } catch {
      return false;
    } finally {
      // Allow the next refresh attempt after this one settles.
      // Defer the clear so concurrent awaiters all see the same result.
      setTimeout(() => {
        refreshInFlight = null;
      }, 0);
    }
  })();

  return refreshInFlight;
}

async function doFetch(
  method: string,
  path: string,
  bodyContent: string | URLSearchParams | FormData | undefined,
  baseHeaders: Record<string, string>,
  signal?: AbortSignal,
): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      method,
      headers: { ...getAuthHeader(), ...baseHeaders },
      body: bodyContent,
      credentials: "include",
      signal,
    });
  } catch (e) {
    // The caller gave the request up: that says nothing about the
    // server, and is the caller's own error to recognise (AbortError).
    if (signal?.aborted) throw e;
    // fetch rejects only when the server never answered (no network,
    // server down, wrong network). On native this flips the app into
    // offline mode instead of surfacing raw errors on every screen.
    reportServerUnreachable();
    throw new Error(m.error_server_unreachable());
  }
  reportServerReachable();
  return res;
}

/** One request, answered: signed, retried once after a silent token
 *  refresh, and with a failure turned into an Error that carries the
 *  server's reason in the reader's language and the status. Every call
 *  goes through here — a JSON body, a form with a file, a stream. */
async function send(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
  signal?: AbortSignal,
): Promise<Response> {
  const baseHeaders: Record<string, string> = { ...extraHeaders };

  let bodyContent: string | URLSearchParams | FormData | undefined;
  if (body instanceof URLSearchParams || body instanceof FormData) {
    // (The browser writes the Content-Type, boundary included.)
    bodyContent = body;
  } else if (body !== undefined) {
    baseHeaders["Content-Type"] = "application/json";
    bodyContent = JSON.stringify(body);
  }

  let res = await doFetch(method, path, bodyContent, baseHeaders, signal);

  // On 401, try to silently refresh the access token once and retry.
  // Skip for the auth endpoints themselves to avoid infinite loops.
  const isAuthEndpoint =
    path.startsWith("/auth/login") ||
    path.startsWith("/auth/refresh") ||
    path.startsWith("/auth/logout");
  if (res.status === 401 && !isAuthEndpoint && typeof window !== "undefined") {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await doFetch(method, path, bodyContent, baseHeaders, signal);
    }
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      message = errorMessage(await res.json()) ?? message;
    } catch {
      // ignore
    }

    // Auto-redirect on persistent 401 (refresh already failed above).
    // Only when online — offline 401s may be stale/proxy responses.
    if (res.status === 401 && typeof window !== "undefined") {
      if (getIsOnline() && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }

    // Callers that need to react to specific statuses (e.g. the sync
    // engine unlinking on 404) get it alongside the translated message.
    const error = new Error(message) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res;
}

async function request(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
  signal?: AbortSignal,
): Promise<unknown> {
  const res = await send(method, path, body, extraHeaders, signal);

  if (res.status === 204) {
    return null;
  }
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json();
  }
  return res.text();
}

/** `signal` aborts the request: the promise then rejects with the
 *  signal's AbortError, and the connection is not counted as lost. */
export function get(
  path: string,
  opts?: { signal?: AbortSignal },
): Promise<unknown> {
  return request("GET", path, undefined, undefined, opts?.signal);
}

export function post(
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<unknown> {
  return request("POST", path, body, extraHeaders);
}

/** POST whose answer is read as it arrives (a stream): the Response
 *  itself, already known to be a success. */
export function postForStream(path: string, body?: unknown): Promise<Response> {
  return send("POST", path, body);
}

export function put(path: string, body?: unknown): Promise<unknown> {
  return request("PUT", path, body);
}

export function patch(path: string, body?: unknown): Promise<unknown> {
  return request("PATCH", path, body);
}

export function del(path: string): Promise<unknown> {
  return request("DELETE", path);
}
