/**
 * OPDS catalog sources — the user's list of third-party catalogs to browse.
 *
 * Device-owned and deliberately NOT scoped per BeePub server (unlike the
 * offline manifest): catalogs are independent of the connection, like the
 * local library they download into. Credentials are stored in plaintext
 * Preferences — the same posture as the auth tokens in localStorage; the
 * app has no secure storage today.
 */
import { Preferences } from "@capacitor/preferences";

const CATALOGS_KEY = "opds-catalogs";

export interface OpdsCatalog {
  id: string;
  name: string;
  /** Root feed URL, https, trailing slashes trimmed. */
  url: string;
  username?: string;
  password?: string;
  addedAt: string;
}

export interface OpdsCatalogInput {
  name: string;
  url: string;
  username?: string;
  password?: string;
}

async function getAll(): Promise<OpdsCatalog[]> {
  const { value } = await Preferences.get({ key: CATALOGS_KEY });
  if (!value) return [];
  try {
    return JSON.parse(value) as OpdsCatalog[];
  } catch {
    return [];
  }
}

async function saveAll(catalogs: OpdsCatalog[]): Promise<void> {
  await Preferences.set({ key: CATALOGS_KEY, value: JSON.stringify(catalogs) });
}

function normalize(input: OpdsCatalogInput): OpdsCatalogInput {
  return {
    name: input.name.trim(),
    url: input.url.trim().replace(/\/+$/, ""),
    // Empty credential fields mean "no auth", not auth with empty strings.
    username: input.username?.trim() || undefined,
    password: input.password || undefined,
  };
}

export async function listCatalogs(): Promise<OpdsCatalog[]> {
  return getAll();
}

export async function getCatalog(id: string): Promise<OpdsCatalog | null> {
  const catalogs = await getAll();
  return catalogs.find((c) => c.id === id) ?? null;
}

export async function addCatalog(
  input: OpdsCatalogInput,
): Promise<OpdsCatalog> {
  const catalog: OpdsCatalog = {
    id: crypto.randomUUID(),
    ...normalize(input),
    addedAt: new Date().toISOString(),
  };
  const catalogs = await getAll();
  catalogs.push(catalog);
  await saveAll(catalogs);
  return catalog;
}

export async function updateCatalog(
  id: string,
  input: OpdsCatalogInput,
): Promise<OpdsCatalog | null> {
  const catalogs = await getAll();
  const index = catalogs.findIndex((c) => c.id === id);
  if (index === -1) return null;
  catalogs[index] = { ...catalogs[index], ...normalize(input) };
  await saveAll(catalogs);
  return catalogs[index];
}

export async function removeCatalog(id: string): Promise<void> {
  const catalogs = await getAll();
  await saveAll(catalogs.filter((c) => c.id !== id));
}
