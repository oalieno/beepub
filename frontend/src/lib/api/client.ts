const SERVER_URL_KEY = "serverUrl";

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
      if (err.detail) message = String(err.detail);
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
