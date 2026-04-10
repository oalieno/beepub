import * as m from "$lib/paraglide/messages.js";

const SERVER_URL_KEY = "serverUrl";

const ERROR_MAP: Record<string, () => string> = {
  "Access denied": () => m.error_access_denied(),
  "Account is disabled": () => m.error_account_disabled(),
  "An illustration already exists for this text selection": () =>
    m.error_illustration_exists(),
  "Book already in library": () => m.error_book_in_library(),
  "Book already in shelf": () => m.error_book_in_shelf(),
  "Book not found": () => m.error_book_not_found(),
  "Book not in library": () => m.error_book_not_in_library(),
  "Book not in shelf": () => m.error_book_not_in_shelf(),
  "Bookshelf not found": () => m.error_bookshelf_not_found(),
  "Calibre library already linked": () => m.error_calibre_already_linked(),
  "Cannot add books to a Calibre library": () => m.error_calibre_no_add(),
  "Cannot delete yourself": () => m.error_cannot_delete_self(),
  "Cannot demote the last admin": () => m.error_cannot_demote_last_admin(),
  "Cannot upload to a Calibre library": () => m.error_calibre_no_upload(),
  "Conversation not found": () => m.error_conversation_not_found(),
  "Cover not found": () => m.error_cover_not_found(),
  "Current password is incorrect": () => m.error_wrong_password(),
  "Description must be 2000 characters or less": () =>
    m.error_description_too_long(),
  "Download permission required": () => m.error_download_permission(),
  "External metadata not found": () => m.error_metadata_not_found(),
  "File not found": () => m.error_file_not_found(),
  "Gemini API key not configured": () => m.error_gemini_not_configured(),
  "Goal must be between 60 and 86400 seconds (1 min to 24 hrs)": () =>
    m.error_goal_range(),
  "Highlight not found": () => m.error_highlight_not_found(),
  "Illustration not found": () => m.error_illustration_not_found(),
  "Image file not found": () => m.error_image_not_found(),
  "Image not ready": () => m.error_image_not_ready(),
  "Invalid credentials": () => m.error_invalid_credentials(),
  "Invalid source": () => m.error_invalid_source(),
  "Library not found": () => m.error_library_not_found(),
  "No accessible books found": () => m.error_no_books_found(),
  "No metadata.db found at path": () => m.error_no_metadata_db(),
  "Not a Calibre library": () => m.error_not_calibre(),
  "Only EPUB files are supported": () => m.error_epub_only(),
  "OpenAI base URL not configured": () => m.error_openai_not_configured(),
  "Path not found in EPUB": () => m.error_path_not_in_epub(),
  "Rating must be 1-5": () => m.error_rating_range(),
  "Registration is currently closed": () => m.error_registration_closed(),
  "Report not found": () => m.error_report_not_found(),
  "Semantic search is not configured": () => m.error_search_not_configured(),
  "Sync already in progress": () => m.error_sync_in_progress(),
  "User not found": () => m.error_user_not_found(),
  "Username already exists": () => m.error_username_exists(),
};

export function getServerUrl(): string {
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem(SERVER_URL_KEY);
    if (stored) return stored;
  }
  return import.meta.env.VITE_API_BASE || "";
}

export function setServerUrl(url: string): void {
  localStorage.setItem(SERVER_URL_KEY, url.replace(/\/$/, ""));
}

export function hasServerUrl(): boolean {
  if (typeof window !== "undefined") {
    return !!localStorage.getItem(SERVER_URL_KEY);
  }
  return !!(import.meta.env.VITE_API_BASE as string);
}

export function apiBase(): string {
  return getServerUrl() + "/api";
}

/**
 * Cover image URL. Web uses nginx fast path (/covers/), native uses API.
 */
export function coverUrl(bookId: string): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const native =
    typeof window !== "undefined" &&
    ((window as any).Capacitor?.isNativePlatform?.() ?? false);
  return native
    ? `${apiBase()}/books/${bookId}/cover`
    : `/covers/${bookId}.jpg`;
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

async function refreshAccessToken(): Promise<boolean> {
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
  bodyContent: string | URLSearchParams | undefined,
  baseHeaders: Record<string, string>,
): Promise<Response> {
  return fetch(`${apiBase()}${path}`, {
    method,
    headers: { ...getAuthHeader(), ...baseHeaders },
    body: bodyContent,
    credentials: "include",
  });
}

async function request(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<unknown> {
  const baseHeaders: Record<string, string> = { ...extraHeaders };

  let bodyContent: string | URLSearchParams | undefined;
  if (body instanceof URLSearchParams) {
    bodyContent = body;
  } else if (body !== undefined) {
    baseHeaders["Content-Type"] = "application/json";
    bodyContent = JSON.stringify(body);
  }

  let res = await doFetch(method, path, bodyContent, baseHeaders);

  // On 401, try to silently refresh the access token once and retry.
  // Skip for the auth endpoints themselves to avoid infinite loops.
  const isAuthEndpoint =
    path.startsWith("/auth/login") ||
    path.startsWith("/auth/refresh") ||
    path.startsWith("/auth/logout");
  if (res.status === 401 && !isAuthEndpoint && typeof window !== "undefined") {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await doFetch(method, path, bodyContent, baseHeaders);
    }
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const err = (await res.json()) as { detail?: string };
      if (err.detail) {
        const detail = String(err.detail);
        const translated = ERROR_MAP[detail];
        message = translated ? translated() : detail;
      }
    } catch {
      // ignore
    }

    // Auto-redirect on persistent 401 (refresh already failed above).
    // Only when online — offline 401s may be stale/proxy responses.
    if (res.status === 401 && typeof window !== "undefined") {
      const { getIsOnline } = await import("$lib/services/network");
      if (getIsOnline() && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }

    throw new Error(message);
  }

  if (res.status === 204) {
    return null;
  }
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json();
  }
  return res.text();
}

export function get(path: string): Promise<unknown> {
  return request("GET", path);
}

export function post(
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<unknown> {
  return request("POST", path, body, extraHeaders);
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
