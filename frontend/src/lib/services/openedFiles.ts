/**
 * Book files handed to the app by iOS — "Open in BeePub" from Files, the
 * share sheet, AirDrop, Mail. The native side (AppDelegate) copies each
 * one into Caches/opened-books/ and fires a window event; files that
 * arrive before the web app is up simply wait there until it looks.
 *
 * Where a file goes is the reader's call (the dialog in the app layout):
 * the device's library or a server library. Both paths reuse the normal
 * machinery — importLocalBook and the upload queue — and report in the
 * transfer panel.
 */
import { writable } from "svelte/store";

import { isLocalMode } from "$lib/api/client";
import * as m from "$lib/paraglide/messages.js";
import {
  addTransfer,
  removeTransfer,
  updateTransfer,
} from "$lib/stores/transfers";

/** Must match AppDelegate.swift. */
const INBOX = "opened-books";
export const OPENED_FILE_EVENT = "beepubFileOpened";

/** What the server's upload accepts (the library upload dialog's list). */
export const SERVER_FORMATS = [".epub", ".txt", ".mobi", ".azw3", ".cbz"];
/** What the device library reads. */
export const DEVICE_FORMATS = [".epub"];

export function hasFormat(file: File, formats: string[]): boolean {
  const name = file.name.toLowerCase();
  return formats.some((ext) => name.endsWith(ext));
}

/** Native writes `<stamp>_<original name>`; the stamp keeps two files of
 *  the same name apart. */
function displayName(stored: string): string {
  const i = stored.indexOf("_");
  return i >= 0 ? stored.slice(i + 1) : stored;
}

let lastPass: Promise<unknown> = Promise.resolve();

/**
 * Take every waiting file: read into memory, then removed from the inbox
 * so it is offered once. Passes run one after another, so a file that
 * lands mid-pass is caught by the next call, never taken twice.
 */
export function takeOpenedFiles(): Promise<File[]> {
  const pass = lastPass.then(readInbox, readInbox);
  lastPass = pass.catch(() => {});
  return pass;
}

async function readInbox(): Promise<File[]> {
  const { Filesystem, Directory } = await import("@capacitor/filesystem");
  const { Capacitor } = await import("@capacitor/core");
  let names: { name: string; uri: string; type: string }[];
  try {
    const res = await Filesystem.readdir({
      path: INBOX,
      directory: Directory.Cache,
    });
    names = res.files.filter((f) => f.type === "file");
  } catch {
    return []; // No inbox yet: nothing was ever opened.
  }
  names.sort((a, b) => a.name.localeCompare(b.name));
  const files: File[] = [];
  for (const entry of names) {
    try {
      const res = await fetch(Capacitor.convertFileSrc(entry.uri));
      if (!res.ok) throw new Error(String(res.status));
      files.push(new File([await res.blob()], displayName(entry.name)));
    } catch {
      // Unreadable: dropped below all the same, not offered forever.
    }
    await Filesystem.deleteFile({
      path: `${INBOX}/${entry.name}`,
      directory: Directory.Cache,
    }).catch(() => {});
  }
  return files;
}

/** Set when a book lands on the device, for a shelf that is on screen. */
export const deviceImported = writable<number>(0);

let chain: Promise<void> = Promise.resolve();

/** Into the device's library, one at a time, each a transfer row. */
export function importToDevice(files: File[]): void {
  const rows = files.map((file) => ({
    file,
    transferId: addTransfer({ kind: "import", title: file.name }),
  }));
  chain = chain.then(async () => {
    for (const row of rows) await importOne(row.file, row.transferId);
  });
}

async function importOne(file: File, transferId: string): Promise<void> {
  // The shelf is only reachable in the device library; from the server
  // side the row just says it landed.
  const href = (id: string) => (isLocalMode() ? `/local/${id}` : undefined);
  if (!hasFormat(file, DEVICE_FORMATS)) {
    updateTransfer(transferId, {
      status: "failed",
      error: m.opened_file_device_epub_only(),
    });
    return;
  }
  updateTransfer(transferId, { status: "running" });
  const { importLocalBook, DuplicateBookError, InvalidEpubError } =
    await import("$lib/services/localLibrary");
  try {
    const entry = await importLocalBook(file);
    updateTransfer(transferId, {
      status: "done",
      title: entry.title,
      href: href(entry.id),
    });
    deviceImported.set(Date.now());
  } catch (err) {
    if (err instanceof DuplicateBookError) {
      updateTransfer(transferId, {
        status: "duplicate",
        title: err.existing.title,
        href: href(err.existing.id),
      });
    } else {
      updateTransfer(transferId, {
        status: "failed",
        error:
          err instanceof InvalidEpubError
            ? m.local_import_invalid()
            : ((err as Error).message ?? ""),
        retry: () => {
          removeTransfer(transferId);
          importToDevice([file]);
        },
      });
    }
  }
}
