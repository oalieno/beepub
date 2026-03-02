const baseURL = '/api';

async function request(
  method: string,
  path: string,
  body?: unknown,
  token?: string | null,
  extraHeaders?: Record<string, string>
): Promise<unknown> {
  const headers: Record<string, string> = {
    ...extraHeaders,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let bodyContent: string | URLSearchParams | undefined;
  if (body instanceof URLSearchParams) {
    bodyContent = body;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
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
      const err = await res.json() as { detail?: string };
      if (err.detail) message = String(err.detail);
    } catch {
      // ignore
    }

    // Auto-logout and redirect on expired/invalid token
    if (res.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      document.cookie = 'token=; Max-Age=0; path=/';
      window.location.href = '/login';
    }

    throw new Error(message);
  }

  if (res.status === 204) {
    return null;
  }
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return res.json();
  }
  return res.text();
}

export function get(path: string, token?: string | null): Promise<unknown> {
  return request('GET', path, undefined, token);
}

export function post(
  path: string,
  body?: unknown,
  token?: string | null,
  extraHeaders?: Record<string, string>
): Promise<unknown> {
  return request('POST', path, body, token, extraHeaders);
}

export function put(path: string, body?: unknown, token?: string | null): Promise<unknown> {
  return request('PUT', path, body, token);
}

export function del(path: string, token?: string | null): Promise<unknown> {
  return request('DELETE', path, undefined, token);
}
