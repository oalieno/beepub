/**
 * The catalog list for the current side. The two libraries each have
 * their own: the device's (local mode, in Preferences, downloads onto the
 * device) and the server's (shared, admin-managed, imports into a server
 * library). Pages ask here and never mix the two.
 */
import { isLocalMode } from "$lib/api/client";
import { isNative } from "$lib/platform";

export type CatalogSide = "device" | "server";

export interface CatalogInfo {
  id: string;
  name: string;
  url: string;
  /** Device: always known. Server: admins only. */
  username: string | null;
  /** Device only — the server never sends it back. */
  password: string | null;
  hasCredentials: boolean;
}

export interface CatalogInput {
  name: string;
  url: string;
  username?: string;
  /** Server: omitted keeps the stored password. */
  password?: string;
}

export function catalogSide(): CatalogSide {
  return isNative() && isLocalMode() ? "device" : "server";
}

type DeviceCatalog = import("$lib/services/opdsCatalogs").OpdsCatalog;
type ServerCatalog = import("./server").ServerCatalog;

function fromDevice(c: DeviceCatalog): CatalogInfo {
  return {
    id: c.id,
    name: c.name,
    url: c.url,
    username: c.username ?? null,
    password: c.password ?? null,
    hasCredentials: !!c.username,
  };
}

function fromServer(c: ServerCatalog): CatalogInfo {
  return {
    id: c.id,
    name: c.name,
    url: c.url,
    username: c.username,
    password: null,
    hasCredentials: c.has_credentials,
  };
}

export async function listCatalogs(side: CatalogSide): Promise<CatalogInfo[]> {
  if (side === "device") {
    const { listCatalogs } = await import("$lib/services/opdsCatalogs");
    return (await listCatalogs()).map(fromDevice);
  }
  const { serverCatalogs } = await import("./server");
  return (await serverCatalogs.list()).map(fromServer);
}

export async function getCatalog(
  side: CatalogSide,
  id: string,
): Promise<CatalogInfo | null> {
  if (side === "device") {
    const { getCatalog } = await import("$lib/services/opdsCatalogs");
    const found = await getCatalog(id);
    return found ? fromDevice(found) : null;
  }
  const { serverCatalogs } = await import("./server");
  try {
    return fromServer(await serverCatalogs.get(id));
  } catch (err) {
    if ((err as { status?: number }).status === 404) return null;
    throw err;
  }
}

export async function saveCatalog(
  side: CatalogSide,
  id: string | null,
  input: CatalogInput,
): Promise<CatalogInfo | null> {
  if (side === "device") {
    const { addCatalog, updateCatalog } =
      await import("$lib/services/opdsCatalogs");
    const saved = id ? await updateCatalog(id, input) : await addCatalog(input);
    return saved ? fromDevice(saved) : null;
  }
  const { serverCatalogs } = await import("./server");
  const body = {
    name: input.name,
    url: input.url,
    username: input.username?.trim() || undefined,
    password: input.password || undefined,
  };
  return fromServer(
    id
      ? await serverCatalogs.update(id, body)
      : await serverCatalogs.create(body),
  );
}

export async function removeCatalog(
  side: CatalogSide,
  id: string,
): Promise<void> {
  if (side === "device") {
    const { removeCatalog } = await import("$lib/services/opdsCatalogs");
    await removeCatalog(id);
    return;
  }
  const { serverCatalogs } = await import("./server");
  await serverCatalogs.remove(id);
}
