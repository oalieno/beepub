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

export function getAuthHeader(): Record<string, string> {
  if (typeof window !== "undefined") {
    // Only send Authorization header in native (Capacitor) mode.
    // Web mode relies on HttpOnly cookies; a stale Bearer token would
    // override the valid cookie (backend prioritises Bearer over cookie).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const isNative = (window as any).Capacitor?.isNativePlatform?.() ?? false;
    if (!isNative) return {};
    const token = localStorage.getItem("token");
    if (token) return { Authorization: `Bearer ${token}` };
  }
  return {};
}

async function request(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<unknown> {
  const headers: Record<string, string> = {
    ...getAuthHeader(),
    ...extraHeaders,
  };

  let bodyContent: string | URLSearchParams | undefined;
  if (body instanceof URLSearchParams) {
    bodyContent = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    bodyContent = JSON.stringify(body);
  }

  const res = await fetch(`${apiBase()}${path}`, {
    method,
    headers,
    body: bodyContent,
  });

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

    // Auto-redirect on expired/invalid token (only when online —
    // offline 401s may be stale/proxy responses, token could still be valid)
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
