const baseURL = "/api";

async function request(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<unknown> {
  const headers: Record<string, string> = {
    ...extraHeaders,
  };

  let bodyContent: string | URLSearchParams | undefined;
  if (body instanceof URLSearchParams) {
    bodyContent = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    bodyContent = JSON.stringify(body);
  }

  const res = await fetch(`${baseURL}${path}`, {
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

    // Auto-redirect on expired/invalid token
    if (res.status === 401 && typeof window !== "undefined") {
      if (window.location.pathname !== "/login") {
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
