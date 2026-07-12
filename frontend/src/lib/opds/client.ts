/**
 * OPDS transport over CapacitorHttp — explicit native requests, because
 * third-party catalog servers don't allow-list the capacitor:// origin the
 * way our own backend's CORS config does, so window.fetch is a dead end.
 *
 * Deliberately NOT the global CapacitorHttp fetch patch
 * (plugins.CapacitorHttp.enabled): that would reroute every request in the
 * app and change auth/streaming semantics everywhere at once. Only
 * this module talks to catalog servers.
 */
import { CapacitorHttp, type HttpResponse } from "@capacitor/core";

import { uint8ToBase64 } from "$lib/services/base64";

import {
  parseOpdsFeed,
  parseOpenSearchDescription,
  type OpdsFeed,
} from "./parse";

export interface OpdsCredentials {
  username: string;
  password: string;
}

export type OpdsErrorKind = "auth" | "http" | "network" | "parse";

/** Typed transport/parse failure; the UI translates by `kind`. */
export class OpdsError extends Error {
  constructor(
    public readonly kind: OpdsErrorKind,
    public readonly status?: number,
    cause?: unknown,
  ) {
    super(`OPDS ${kind} error${status ? ` (${status})` : ""}`, { cause });
    this.name = "OpdsError";
  }
}

const CONNECT_TIMEOUT = 10_000;
const READ_TIMEOUT = 20_000;

const FEED_ACCEPT =
  "application/atom+xml;profile=opds-catalog, application/atom+xml;q=0.9, application/xml;q=0.8, */*;q=0.7";

/** Basic auth via uint8ToBase64, not btoa — btoa throws on non-Latin-1
 *  passwords. */
export function basicAuthHeader(creds: OpdsCredentials): string {
  return (
    "Basic " +
    uint8ToBase64(
      new TextEncoder().encode(`${creds.username}:${creds.password}`),
    )
  );
}

export function authHeaders(creds?: OpdsCredentials): Record<string, string> {
  return creds ? { Authorization: basicAuthHeader(creds) } : {};
}

/** Case-insensitive response-header lookup — iOS keeps the server's casing. */
function headerValue(
  headers: Record<string, string> | undefined,
  name: string,
): string | null {
  if (!headers) return null;
  const lower = name.toLowerCase();
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === lower) return value;
  }
  return null;
}

async function get(
  url: string,
  creds: OpdsCredentials | undefined,
  responseType: "text" | "blob",
  accept?: string,
): Promise<HttpResponse> {
  let res: HttpResponse;
  try {
    res = await CapacitorHttp.get({
      url,
      headers: { ...(accept ? { Accept: accept } : {}), ...authHeaders(creds) },
      responseType,
      // Next/search URLs arrive pre-encoded and opaque; re-encoding would
      // double-escape them.
      shouldEncodeUrlParams: false,
      connectTimeout: CONNECT_TIMEOUT,
      readTimeout: READ_TIMEOUT,
    });
  } catch (err) {
    throw new OpdsError("network", undefined, err);
  }
  if (res.status === 401) throw new OpdsError("auth", 401);
  if (res.status >= 400) throw new OpdsError("http", res.status);
  return res;
}

export async function fetchFeed(
  url: string,
  creds?: OpdsCredentials,
): Promise<OpdsFeed> {
  const res = await get(url, creds, "text", FEED_ACCEPT);
  const xml = typeof res.data === "string" ? res.data : String(res.data ?? "");
  try {
    return parseOpdsFeed(xml, url);
  } catch (err) {
    throw new OpdsError("parse", undefined, err);
  }
}

/** The catalog's OpenSearch URL template, or null when unusable — a broken
 *  search description shouldn't take browsing down with it. */
export async function fetchSearchTemplate(
  descUrl: string,
  creds?: OpdsCredentials,
): Promise<string | null> {
  try {
    const res = await get(descUrl, creds, "text");
    const xml =
      typeof res.data === "string" ? res.data : String(res.data ?? "");
    return parseOpenSearchDescription(xml, descUrl);
  } catch {
    return null;
  }
}

/**
 * Fetch a cover/thumbnail as a data URI. Only needed for credentialed
 * catalogs — plain <img> can't send Basic auth. Null on any failure; the
 * grid falls back to the placeholder.
 */
export async function fetchImageDataUri(
  url: string,
  creds: OpdsCredentials,
): Promise<string | null> {
  try {
    // On native, responseType "blob" delivers the body as base64.
    const res = await get(url, creds, "blob");
    if (typeof res.data !== "string" || !res.data) return null;
    const contentType =
      headerValue(res.headers, "content-type")?.split(";")[0] ?? "image/jpeg";
    return `data:${contentType};base64,${res.data}`;
  } catch {
    return null;
  }
}
