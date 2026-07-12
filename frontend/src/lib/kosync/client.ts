/**
 * kosync wire transport over CapacitorHttp — explicit native requests, same
 * posture as the OPDS client: external sync servers don't allow-list the
 * capacitor:// origin, so window.fetch is a dead end, and the global
 * CapacitorHttp fetch patch stays off.
 *
 * Protocol reference: our own backend's /kosync router (and the canonical
 * koreader-sync-server). Auth is `x-auth-user` + `x-auth-key = md5(password)`
 * on every request; registration sends the same md5 as the password, so the
 * plaintext never needs to be stored or resent.
 */
import { CapacitorHttp, type HttpResponse } from "@capacitor/core";

export interface KosyncCredentials {
  /** https, no trailing slash — endpoint paths are appended verbatim. */
  serverUrl: string;
  username: string;
  /** md5(password), lowercase hex. */
  userkey: string;
}

export interface KosyncProgressRecord {
  document: string;
  /** Opaque position string — a crengine xpointer for EPUBs. */
  progress: string | null;
  /** 0..1 — the kosync wire scale, NOT the 0..100 marker scale. */
  percentage: number;
  device: string | null;
  deviceId: string | null;
  /** Unix seconds. */
  timestamp: number | null;
}

export interface KosyncPushPayload {
  document: string;
  progress: string;
  /** 0..1. */
  percentage: number;
  device: string;
  device_id: string;
}

export type KosyncErrorKind =
  | "auth"
  | "http"
  | "network"
  | "parse"
  | "conflict";

/** Typed transport failure; the UI translates by `kind`. */
export class KosyncError extends Error {
  constructor(
    public readonly kind: KosyncErrorKind,
    public readonly status?: number,
    public readonly serverMessage?: string,
    cause?: unknown,
  ) {
    super(`kosync ${kind} error${status ? ` (${status})` : ""}`, { cause });
    this.name = "KosyncError";
  }
}

const CONNECT_TIMEOUT = 10_000;
const READ_TIMEOUT = 20_000;

// The canonical server 412s requests without the vendored accept type.
const ACCEPT = "application/vnd.koreader.v1+json";

function headers(creds?: KosyncCredentials): Record<string, string> {
  return {
    Accept: ACCEPT,
    ...(creds
      ? { "x-auth-user": creds.username, "x-auth-key": creds.userkey }
      : {}),
  };
}

/** CapacitorHttp delivers JSON bodies as parsed objects or raw strings
 *  depending on platform and content-type — normalize defensively. */
function bodyOf(res: HttpResponse): Record<string, unknown> {
  const data: unknown = res.data;
  if (data && typeof data === "object") return data as Record<string, unknown>;
  if (typeof data === "string" && data) {
    try {
      const parsed: unknown = JSON.parse(data);
      if (parsed && typeof parsed === "object")
        return parsed as Record<string, unknown>;
    } catch {
      // Fall through — HTML error pages, captive portals.
    }
  }
  return {};
}

function messageOf(res: HttpResponse): string | undefined {
  const message = bodyOf(res)["message"];
  return typeof message === "string" ? message : undefined;
}

async function request(options: {
  method: "GET" | "POST" | "PUT";
  url: string;
  creds?: KosyncCredentials;
  data?: unknown;
}): Promise<HttpResponse> {
  try {
    return await CapacitorHttp.request({
      method: options.method,
      url: options.url,
      headers: {
        ...headers(options.creds),
        ...(options.data !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
      },
      data: options.data,
      shouldEncodeUrlParams: false,
      connectTimeout: CONNECT_TIMEOUT,
      readTimeout: READ_TIMEOUT,
    });
  } catch (err) {
    throw new KosyncError("network", undefined, undefined, err);
  }
}

/** GET /users/auth — throws on anything but an authorized 200. */
export async function verifyAuth(creds: KosyncCredentials): Promise<void> {
  const res = await request({
    method: "GET",
    url: `${creds.serverUrl}/users/auth`,
    creds,
  });
  if (res.status === 401) throw new KosyncError("auth", 401, messageOf(res));
  if (res.status >= 400)
    throw new KosyncError("http", res.status, messageOf(res));
  // Status alone can lie: a non-kosync URL behind a login redirect answers
  // 200 with HTML (CapacitorHttp follows the 302). Require the protocol's
  // actual success body so a bad URL can't save a silently-broken account.
  if (bodyOf(res)["authorized"] !== "OK")
    throw new KosyncError("parse", res.status);
}

/**
 * POST /users/create with the md5 key as the password (the stock-client
 * convention — later x-auth-keys are compared against it verbatim).
 * Canonical servers answer 201; 402 means the username is taken; BeePub
 * servers always refuse with 403 and a user-meaningful message.
 */
export async function registerAccount(creds: KosyncCredentials): Promise<void> {
  const res = await request({
    method: "POST",
    url: `${creds.serverUrl}/users/create`,
    data: { username: creds.username, password: creds.userkey },
  });
  // Canonical servers answer 201; tolerate 200 from reimplementations —
  // the verifyAuth that always follows catches false positives.
  if (res.status === 200 || res.status === 201) return;
  if (res.status === 402)
    throw new KosyncError("conflict", 402, messageOf(res));
  throw new KosyncError("http", res.status, messageOf(res));
}

/**
 * GET /syncs/progress/{document}. An empty record is a 200 whose body lacks
 * `percentage` (the stock client's "no progress" signal) — returned as null.
 */
export async function fetchProgress(
  creds: KosyncCredentials,
  document: string,
): Promise<KosyncProgressRecord | null> {
  const res = await request({
    method: "GET",
    url: `${creds.serverUrl}/syncs/progress/${document}`,
    creds,
  });
  if (res.status === 401) throw new KosyncError("auth", 401);
  if (res.status >= 400)
    throw new KosyncError("http", res.status, messageOf(res));
  const body = bodyOf(res);
  const percentage = body["percentage"];
  if (typeof percentage !== "number") return null;
  const progress = body["progress"];
  const device = body["device"];
  const deviceId = body["device_id"];
  const timestamp = body["timestamp"];
  return {
    document,
    progress: typeof progress === "string" ? progress : null,
    percentage: Math.min(1, Math.max(0, percentage)),
    device: typeof device === "string" ? device : null,
    deviceId: typeof deviceId === "string" ? deviceId : null,
    timestamp: typeof timestamp === "number" ? timestamp : null,
  };
}

/** PUT /syncs/progress — a blind last-write-wins overwrite on the server. */
export async function pushProgress(
  creds: KosyncCredentials,
  payload: KosyncPushPayload,
): Promise<void> {
  const res = await request({
    method: "PUT",
    url: `${creds.serverUrl}/syncs/progress`,
    creds,
    data: payload,
  });
  if (res.status === 401) throw new KosyncError("auth", 401);
  if (res.status >= 400)
    throw new KosyncError("http", res.status, messageOf(res));
}
