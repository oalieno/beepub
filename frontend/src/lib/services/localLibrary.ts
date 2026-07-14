/**
 * Device-local book library — EPUBs imported from the file picker, owned by
 * the device rather than any server.
 *
 * Local books have no server identity, so the manifest is unscoped and books
 * are keyed by client-generated UUIDs. Each entry carries the KOReader
 * partial-md5 digest — the cross-device file identity that later links a
 * local book to server records (sync) and kosync documents, and that makes
 * re-imports of the same file detectable.
 */
import { Filesystem, Directory } from "@capacitor/filesystem";
import { Preferences } from "@capacitor/preferences";
import { Capacitor } from "@capacitor/core";
import { getServerUrl } from "$lib/api/client";
import { computePartialMd5 } from "$lib/services/partialMd5";
import { uint8ToBase64 } from "$lib/services/base64";

const MANIFEST_KEY = "local-library";
const LINKS_KEY_PREFIX = "local-links";

// Filesystem.appendFile concatenates base64 strings, so each chunk must be
// a multiple of 3 bytes — otherwise per-chunk padding corrupts the file.
const WRITE_CHUNK = 3 * 1024 * 1024;

export interface LocalBookEntry {
  id: string;
  title: string;
  authors: string[];
  language: string | null;
  identifier: string | null;
  digest: string;
  filePath: string;
  coverPath: string | null;
  fileSize: number;
  importedAt: string;
}

/** The same file (by digest) is already in the library. */
export class DuplicateBookError extends Error {
  constructor(public readonly existing: LocalBookEntry) {
    super(`Book already imported: ${existing.title}`);
    this.name = "DuplicateBookError";
  }
}

/** The picked file could not be parsed as an EPUB. */
export class InvalidEpubError extends Error {
  constructor(cause: unknown) {
    super("Not a readable EPUB file", { cause });
    this.name = "InvalidEpubError";
  }
}

// Reading state for local books lives in sibling Preferences keys; the
// library owns the naming so deletion can clear them (see removeLocalBook).
export const localProgressKey = (bookId: string) => `local-progress:${bookId}`;
export const localHighlightsKey = (bookId: string) =>
  `local-highlights:${bookId}`;
export const localInteractionKey = (bookId: string) =>
  `local-interaction:${bookId}`;

async function getManifest(): Promise<LocalBookEntry[]> {
  const { value } = await Preferences.get({ key: MANIFEST_KEY });
  if (!value) return [];
  try {
    return JSON.parse(value) as LocalBookEntry[];
  } catch {
    return [];
  }
}

async function saveManifest(entries: LocalBookEntry[]): Promise<void> {
  await Preferences.set({ key: MANIFEST_KEY, value: JSON.stringify(entries) });
}

export async function listLocalBooks(): Promise<LocalBookEntry[]> {
  return getManifest();
}

export async function getLocalBook(
  bookId: string,
): Promise<LocalBookEntry | null> {
  const manifest = await getManifest();
  return manifest.find((e) => e.id === bookId) ?? null;
}

export async function getLocalStorageUsage(): Promise<number> {
  const manifest = await getManifest();
  return manifest.reduce((sum, e) => sum + e.fileSize, 0);
}

// --- Server links ---
//
// A link ties a local book to a matching server book (same file, by
// digest). Links are scoped per server URL — a server book id only means
// anything on its own server. The manifest itself stays server-free.

function linksKey(): string | null {
  const server = getServerUrl().replace(/\/+$/, "");
  return server ? `${LINKS_KEY_PREFIX}:${server}` : null;
}

/** Local-book-id → server-book-id map for the configured server. */
export async function getLocalBookLinks(): Promise<Record<string, string>> {
  const key = linksKey();
  if (!key) return {};
  const { value } = await Preferences.get({ key });
  if (!value) return {};
  try {
    return JSON.parse(value) as Record<string, string>;
  } catch {
    return {};
  }
}

export async function setLocalBookLink(
  localBookId: string,
  serverBookId: string,
): Promise<void> {
  const key = linksKey();
  if (!key) return;
  const links = await getLocalBookLinks();
  links[localBookId] = serverBookId;
  await Preferences.set({ key, value: JSON.stringify(links) });
}

export async function clearLocalBookLink(localBookId: string): Promise<void> {
  const key = linksKey();
  if (!key) return;
  const links = await getLocalBookLinks();
  if (!(localBookId in links)) return;
  delete links[localBookId];
  await Preferences.set({ key, value: JSON.stringify(links) });
}

/** Drop a deleted book's links across every server, not just the current
 *  one — the local id is gone for good. */
async function clearLinksEverywhere(localBookId: string): Promise<void> {
  try {
    const { keys } = await Preferences.keys();
    for (const key of keys) {
      if (!key.startsWith(`${LINKS_KEY_PREFIX}:`)) continue;
      const { value } = await Preferences.get({ key });
      if (!value) continue;
      let links: Record<string, string>;
      try {
        links = JSON.parse(value) as Record<string, string>;
      } catch {
        continue;
      }
      if (!(localBookId in links)) continue;
      delete links[localBookId];
      await Preferences.set({ key, value: JSON.stringify(links) });
    }
  } catch {
    // Best-effort cleanup; a stale link entry is harmless.
  }
}

interface ParsedEpub {
  title: string | null;
  authors: string[];
  language: string | null;
  identifier: string | null;
  cover: Blob | null;
}

/**
 * Cover for books without a standard declaration — epub.js only knows
 * properties="cover-image" (EPUB3) and <meta name="cover"> (EPUB2), but
 * e.g. Kadokawa EPUB3s declare the cover only as a guide reference to an
 * XHTML page. Mirror the backend extractor's fallbacks: a manifest image
 * named like a cover, else the first image on the first spine page (cover
 * pages are conventionally spine[0]).
 */
async function fallbackCoverBlob(book: any): Promise<Blob | null> {
  try {
    const manifest: Record<string, { href?: string; type?: string }> =
      book.packaging?.manifest ?? {};
    for (const [id, item] of Object.entries(manifest)) {
      if (
        item?.type?.startsWith("image/") &&
        item.href &&
        /cover/i.test(`${id} ${item.href}`)
      ) {
        const blob = await book.archive.getBlob(book.resolve(item.href));
        if (blob) return blob;
      }
    }

    const section = book.spine?.get(0);
    if (!section) return null;
    await section.load(book.load.bind(book));
    const doc: Document | null = section.document ?? null;
    const img = doc?.querySelector("img[src], image");
    // || not ?? — an empty attribute must fall through to the next form.
    const src =
      img?.getAttribute("src") ||
      img?.getAttribute("xlink:href") ||
      img?.getAttribute("href");
    if (!src) return null;
    // Resolve relative to the page, in the leading-slash root form
    // archive.getBlob expects (it strips the first character).
    const base = new URL(book.resolve(section.href), "https://epub/");
    const path = new URL(src, base).pathname;
    const blob = (await book.archive.getBlob(path)) ?? null;
    return blob?.type?.startsWith("image/") ? blob : null;
  } catch {
    return null;
  }
}

/** Parse metadata and cover from EPUB bytes, in memory, via the epub.js fork. */
async function parseEpub(buf: ArrayBuffer): Promise<ParsedEpub> {
  const Epub = (await import("$lib/epubjs/epub.js")).default;
  // No constructor URL: auto-open swallows failures (it only emits
  // OPEN_FAILED), which would leave us awaiting promises that never settle
  // on a corrupt file. Calling open() ourselves gets a rejecting promise.
  // The fork is untyped JS (same `any` treatment as EpubReader's epubBook).
  const book: any = (Epub as any)();
  try {
    try {
      await book.open(buf);
    } catch (err) {
      throw new InvalidEpubError(err);
    }
    const metadata = book.packaging?.metadata ?? {};
    let cover: Blob | null = null;
    if (book.cover) {
      try {
        cover = (await book.archive.getBlob(book.cover)) ?? null;
      } catch {
        cover = null;
      }
    }
    if (!cover) cover = await fallbackCoverBlob(book);
    return {
      title: metadata.title || null,
      authors: metadata.creator ? [metadata.creator] : [],
      language: metadata.language || null,
      identifier:
        book.packaging?.uniqueIdentifier || metadata.identifier || null,
      cover,
    };
  } finally {
    book.destroy();
  }
}

async function deleteFileQuiet(path: string): Promise<void> {
  try {
    await Filesystem.deleteFile({ path, directory: Directory.Data });
  } catch {
    // Already gone
  }
}

/**
 * Import a picked EPUB file into the local library.
 *
 * Throws DuplicateBookError when the same file (by digest) is already
 * imported and InvalidEpubError when it fails to parse; both are thrown
 * before the library is touched, and a failure mid-write cleans up after
 * itself, so the manifest never references a partial import.
 */
export async function importLocalBook(file: File): Promise<LocalBookEntry> {
  // Digest first — it reads at most 12 KiB, so duplicates are rejected
  // before any parsing or copying happens.
  const digest = await computePartialMd5(file);
  const manifest = await getManifest();
  const existing = manifest.find((e) => e.digest === digest);
  if (existing) throw new DuplicateBookError(existing);

  const parsed = await parseEpub(await file.arrayBuffer());

  const id = crypto.randomUUID();
  const filePath = `local-books/${id}.epub`;
  let coverPath: string | null = null;
  try {
    if (parsed.cover) {
      coverPath = `local-covers/${id}.${parsed.cover.type === "image/png" ? "png" : "jpg"}`;
      await Filesystem.writeFile({
        path: coverPath,
        data: uint8ToBase64(new Uint8Array(await parsed.cover.arrayBuffer())),
        directory: Directory.Data,
        recursive: true,
      });
    }

    await Filesystem.writeFile({
      path: filePath,
      data: "",
      directory: Directory.Data,
      recursive: true,
    });
    for (let offset = 0; offset < file.size; offset += WRITE_CHUNK) {
      const chunk = await file
        .slice(offset, offset + WRITE_CHUNK)
        .arrayBuffer();
      await Filesystem.appendFile({
        path: filePath,
        data: uint8ToBase64(new Uint8Array(chunk)),
        directory: Directory.Data,
      });
    }
  } catch (err) {
    await deleteFileQuiet(filePath);
    if (coverPath) await deleteFileQuiet(coverPath);
    throw err;
  }

  const entry: LocalBookEntry = {
    id,
    title: parsed.title ?? file.name.replace(/\.epub$/i, ""),
    authors: parsed.authors,
    language: parsed.language,
    identifier: parsed.identifier,
    digest,
    filePath,
    coverPath,
    fileSize: file.size,
    importedAt: new Date().toISOString(),
  };
  manifest.push(entry);
  await saveManifest(manifest);
  return entry;
}

/**
 * Delete a local book, its cover, and its reading state.
 *
 * Hard delete is correct while the library is device-only; once sync
 * exists, book deletion needs its own tombstone so it can propagate.
 */
export async function removeLocalBook(bookId: string): Promise<void> {
  const manifest = await getManifest();
  const entry = manifest.find((e) => e.id === bookId);
  if (entry) {
    await deleteFileQuiet(entry.filePath);
    if (entry.coverPath) await deleteFileQuiet(entry.coverPath);
  }
  await saveManifest(manifest.filter((e) => e.id !== bookId));
  await Preferences.remove({ key: localProgressKey(bookId) });
  await Preferences.remove({ key: localHighlightsKey(bookId) });
  await Preferences.remove({ key: localInteractionKey(bookId) });
  await clearLinksEverywhere(bookId);
}

/**
 * Read a local book's EPUB as ArrayBuffer for epub.js.
 *
 * Unlike the download cache, a read failure does NOT drop the manifest
 * entry — the local file is the only copy, so the entry stays visible and
 * deletion is the user's call.
 */
export async function readLocalBookBytes(
  bookId: string,
): Promise<ArrayBuffer | null> {
  const entry = await getLocalBook(bookId);
  if (!entry) return null;
  try {
    const result = await Filesystem.readFile({
      path: entry.filePath,
      directory: Directory.Data,
    });
    if (typeof result.data === "string") {
      const binary = atob(result.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      return bytes.buffer;
    }
    return await (result.data as Blob).arrayBuffer();
  } catch {
    return null;
  }
}

/** Get a WebView-safe cover URI for an entry.
 *  Always re-derives from disk — stored URIs go stale across app restarts. */
export async function getLocalCoverSrc(
  entry: LocalBookEntry,
): Promise<string | null> {
  if (!entry.coverPath) return null;
  try {
    const uriResult = await Filesystem.getUri({
      path: entry.coverPath,
      directory: Directory.Data,
    });
    return Capacitor.convertFileSrc(uriResult.uri);
  } catch {
    return null;
  }
}
