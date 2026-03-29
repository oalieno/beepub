/**
 * Offline book download manager.
 * Uses Capacitor Filesystem + Preferences to download EPUBs for offline reading.
 */
import { Filesystem, Directory } from "@capacitor/filesystem";
import { Preferences } from "@capacitor/preferences";
import { Capacitor } from "@capacitor/core";
import { apiBase, getAuthHeader } from "$lib/api/client";

const MANIFEST_KEY = "offline-manifest";

export interface DownloadEntry {
  bookId: string;
  title: string;
  authors: string[];
  coverPath: string | null;
  filePath: string;
  downloadedAt: string;
  fileSize: number;
}

async function getManifest(): Promise<DownloadEntry[]> {
  const { value } = await Preferences.get({ key: MANIFEST_KEY });
  if (!value) return [];
  try {
    return JSON.parse(value) as DownloadEntry[];
  } catch {
    return [];
  }
}

async function saveManifest(entries: DownloadEntry[]): Promise<void> {
  await Preferences.set({
    key: MANIFEST_KEY,
    value: JSON.stringify(entries),
  });
}

export async function isBookDownloaded(bookId: string): Promise<boolean> {
  const manifest = await getManifest();
  return manifest.some((e) => e.bookId === bookId);
}

export async function getDownloadedBooks(): Promise<DownloadEntry[]> {
  return getManifest();
}

export async function getStorageUsage(): Promise<number> {
  const manifest = await getManifest();
  return manifest.reduce((sum, e) => sum + e.fileSize, 0);
}

/** Convert a Uint8Array to base64 string. */
function uint8ToBase64(uint8: Uint8Array): string {
  let binary = "";
  const chunkSize = 8192;
  for (let i = 0; i < uint8.length; i += chunkSize) {
    binary += String.fromCharCode(...uint8.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

/** Download and cache the book's cover image. Returns a WebView-safe URI. */
async function downloadCover(bookId: string): Promise<string | null> {
  try {
    const url = `${apiBase()}/books/${bookId}/cover`;
    const res = await fetch(url, { headers: getAuthHeader() });
    if (!res.ok) return null;

    const blob = await res.blob();
    const arrayBuffer = await blob.arrayBuffer();
    const base64Data = uint8ToBase64(new Uint8Array(arrayBuffer));

    const coverPath = `covers/${bookId}.jpg`;
    await Filesystem.writeFile({
      path: coverPath,
      data: base64Data,
      directory: Directory.Data,
      recursive: true,
    });

    const uriResult = await Filesystem.getUri({
      path: coverPath,
      directory: Directory.Data,
    });
    return Capacitor.convertFileSrc(uriResult.uri);
  } catch {
    return null;
  }
}

/** Get a WebView-safe cover URI for an existing entry.
 *  Always re-derives from disk — stored coverPath may be stale after app restart. */
export async function getCoverSrc(
  entry: DownloadEntry,
): Promise<string | null> {
  try {
    const uriResult = await Filesystem.getUri({
      path: `covers/${entry.bookId}.jpg`,
      directory: Directory.Data,
    });
    return Capacitor.convertFileSrc(uriResult.uri);
  } catch {
    return null;
  }
}

/**
 * Download a book's EPUB file for offline reading.
 * Also downloads and caches the cover image.
 */
export async function downloadBook(
  bookId: string,
  title: string,
  authors: string[],
  onProgress?: (loaded: number, total: number) => void,
): Promise<void> {
  const filePath = `books/${bookId}.epub`;

  // Fetch with auth headers and track progress
  const url = `${apiBase()}/books/${bookId}/file`;
  const headers = getAuthHeader();
  const res = await fetch(url, { headers });

  if (!res.ok) {
    throw new Error(`Download failed: HTTP ${res.status}`);
  }

  const contentLength = Number(res.headers.get("content-length") || 0);
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("ReadableStream not supported");
  }

  // Read chunks and track progress
  const chunks: Uint8Array[] = [];
  let loaded = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress?.(loaded, contentLength);
  }

  // Combine chunks and write to disk
  const blob = new Blob(chunks as BlobPart[]);
  const arrayBuffer = await blob.arrayBuffer();
  const base64Data = uint8ToBase64(new Uint8Array(arrayBuffer));

  await Filesystem.writeFile({
    path: filePath,
    data: base64Data,
    directory: Directory.Data,
    recursive: true,
  });

  // Also cache the cover image
  const coverPath = await downloadCover(bookId);

  // Update manifest
  const manifest = await getManifest();
  const existing = manifest.findIndex((e) => e.bookId === bookId);
  const entry: DownloadEntry = {
    bookId,
    title,
    authors,
    coverPath,
    filePath,
    downloadedAt: new Date().toISOString(),
    fileSize: loaded,
  };
  if (existing >= 0) {
    manifest[existing] = entry;
  } else {
    manifest.push(entry);
  }
  await saveManifest(manifest);
}

/**
 * Delete a downloaded book and its cached cover.
 */
export async function deleteLocalBook(bookId: string): Promise<void> {
  const manifest = await getManifest();
  const entry = manifest.find((e) => e.bookId === bookId);
  if (entry) {
    try {
      await Filesystem.deleteFile({
        path: entry.filePath,
        directory: Directory.Data,
      });
    } catch {
      // File may already be gone
    }
    try {
      await Filesystem.deleteFile({
        path: `covers/${bookId}.jpg`,
        directory: Directory.Data,
      });
    } catch {
      // Cover may not exist
    }
  }
  await saveManifest(manifest.filter((e) => e.bookId !== bookId));
}

/**
 * Read a downloaded EPUB as ArrayBuffer for epub.js.
 */
export async function readLocalBook(
  bookId: string,
): Promise<ArrayBuffer | null> {
  const manifest = await getManifest();
  const entry = manifest.find((e) => e.bookId === bookId);
  if (!entry) return null;

  try {
    const result = await Filesystem.readFile({
      path: entry.filePath,
      directory: Directory.Data,
    });

    // result.data is base64 string on native
    if (typeof result.data === "string") {
      const binary = atob(result.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      return bytes.buffer;
    }

    // Blob (web fallback)
    return await (result.data as Blob).arrayBuffer();
  } catch {
    // File corrupt or missing — clean up manifest
    await deleteLocalBook(bookId);
    return null;
  }
}
