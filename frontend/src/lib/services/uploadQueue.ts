/**
 * Uploads into a server library, run in the background: the dialog that
 * started them closes at once, each file gets a row in the transfer
 * panel, and the library page refreshes when a batch lands — if it is
 * still the page on screen.
 */
import { writable } from "svelte/store";

import { booksApi } from "$lib/api/books";
import type { LocalBookEntry } from "$lib/services/localLibrary";
import {
  noteSimplifiedUploads,
  type PendingBook,
} from "$lib/services/zhConvert";
import {
  addTransfer,
  removeTransfer,
  updateTransfer,
} from "$lib/stores/transfers";

interface UploadTask {
  title: string;
  /** The book on the server afterwards; duplicate = it was already there. */
  run: () => Promise<{
    status: "done" | "duplicate";
    bookId: string;
    /** The new book reads as Simplified Chinese (see zhConvert). */
    simplified?: PendingBook;
  }>;
}

/** Set when a batch into a library finishes with something new in it. */
export const libraryUploaded = writable<{
  libraryId: string;
  at: number;
} | null>(null);

let chain: Promise<void> = Promise.resolve();

function enqueue(libraryId: string, tasks: UploadTask[]): void {
  const rows = tasks.map((task) => ({
    task,
    transferId: addTransfer({ kind: "upload", title: task.title }),
  }));
  // One upload at a time, batches in the order they were started.
  chain = chain.then(async () => {
    let landed = 0;
    const simplified: PendingBook[] = [];
    for (const { task, transferId } of rows) {
      const result = await runOne(task, transferId, libraryId);
      if (result?.status === "done") landed++;
      if (result?.simplified) simplified.push(result.simplified);
    }
    if (landed > 0) libraryUploaded.set({ libraryId, at: Date.now() });
    noteSimplifiedUploads(simplified);
  });
}

async function runOne(
  task: UploadTask,
  transferId: string,
  libraryId: string,
): Promise<Awaited<ReturnType<UploadTask["run"]>> | null> {
  updateTransfer(transferId, { status: "running" });
  try {
    const result = await task.run();
    updateTransfer(transferId, {
      status: result.status,
      href: `/books/${result.bookId}`,
    });
    return result;
  } catch (e) {
    updateTransfer(transferId, {
      status: "failed",
      error: (e as Error).message,
      retry: () => {
        removeTransfer(transferId);
        enqueue(libraryId, [task]);
      },
    });
    return null;
  }
}

/** Files picked or dropped on a library page. */
export function uploadFiles(files: File[], libraryId: string): void {
  enqueue(
    libraryId,
    files.map((file) => ({
      title: file.name,
      run: async () => {
        const book = await booksApi.upload(file, libraryId);
        return {
          status: "done",
          bookId: book.id,
          simplified: book.zh_simplified
            ? { id: book.id, title: book.display_title ?? file.name }
            : undefined,
        };
      },
    })),
  );
}

/** Books from the device's local library. One the server already has is
 *  linked, not sent again. */
export function uploadLocalBooks(
  entries: LocalBookEntry[],
  libraryId: string,
): void {
  enqueue(
    libraryId,
    entries.map((entry) => ({
      title: entry.title,
      run: async () => {
        const { uploadLocalBook } = await import("$lib/services/uploadLocal");
        const { outcome, serverId } = await uploadLocalBook(entry, libraryId);
        return {
          status: outcome === "linked" ? "duplicate" : "done",
          bookId: serverId,
        };
      },
    })),
  );
}
