/**
 * Offline book download manager.
 * Uses Capacitor Filesystem + Preferences to download EPUBs for offline reading.
 */
import { Filesystem, Directory } from "@capacitor/filesystem";
import { Preferences } from "@capacitor/preferences";
import { apiBase, getAuthHeader } from "$lib/api/client";

const MANIFEST_KEY = "offline-manifest";

export interface DownloadEntry {
  bookId: string;
  title: string;
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

/**
 * Download a book's EPUB file for offline reading.
 * Uses fetch + writeFile to stream the file to disk with auth headers.
 */
export async function downloadBook(
  bookId: string,
  title: string,
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

  // Combine chunks into a single ArrayBuffer
  const blob = new Blob(chunks as BlobPart[]);
  const arrayBuffer = await blob.arrayBuffer();
  const uint8 = new Uint8Array(arrayBuffer);

  // Convert to base64 for Filesystem.writeFile
  let binary = "";
  const chunkSize = 8192;
  for (let i = 0; i < uint8.length; i += chunkSize) {
    binary += String.fromCharCode(...uint8.subarray(i, i + chunkSize));
  }
  const base64Data = btoa(binary);

  await Filesystem.writeFile({
    path: filePath,
    data: base64Data,
    directory: Directory.Data,
    recursive: true,
  });

  // Update manifest
  const manifest = await getManifest();
  const existing = manifest.findIndex((e) => e.bookId === bookId);
  const entry: DownloadEntry = {
    bookId,
    title,
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
 * Delete a downloaded book.
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
