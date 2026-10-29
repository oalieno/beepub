/**
 * Simplified-to-Traditional conversion of server books. Never done
 * unasked: an upload that brings Simplified books ends with a question
 * (ZhUploadPrompt) every time, so the uploader knows it was done. A book
 * already in the library is converted from its page.
 */
import { writable } from "svelte/store";

import { booksApi } from "$lib/api/books";
import {
  addTransfer,
  removeTransfer,
  updateTransfer,
} from "$lib/stores/transfers";
import type { ZhConversion } from "$lib/types";

export interface PendingBook {
  id: string;
  title: string;
}

/** Books an upload just brought in that read as Simplified Chinese. */
export const simplifiedUploads = writable<PendingBook[]>([]);

export function noteSimplifiedUploads(books: PendingBook[]): void {
  if (books.length) simplifiedUploads.update((list) => [...list, ...books]);
}

const PHRASES_KEY = "zh-conversion-phrases";

/** The wording choice made last time, so each dialog starts from it. */
export function rememberedMode(): ZhConversion {
  try {
    const stored = localStorage.getItem(PHRASES_KEY);
    if (stored === "s2tw" || stored === "s2twp") return stored;
  } catch {
    // Storage unavailable: fall through.
  }
  return "s2tw";
}

export function rememberMode(mode: ZhConversion): void {
  try {
    localStorage.setItem(PHRASES_KEY, mode);
  } catch {
    // A convenience only.
  }
}

let chain: Promise<void> = Promise.resolve();

/** Convert several books in the background, one at a time, each with a
 *  row in the transfer panel. */
export function convertBooks(books: PendingBook[], mode: ZhConversion): void {
  const rows = books.map((book) => ({
    book,
    transferId: addTransfer({ kind: "convert", title: book.title }),
  }));
  chain = chain.then(async () => {
    for (const { book, transferId } of rows) {
      updateTransfer(transferId, { status: "running" });
      try {
        await booksApi.convertZh(book.id, mode);
        updateTransfer(transferId, {
          status: "done",
          href: `/books/${book.id}`,
        });
      } catch (e) {
        updateTransfer(transferId, {
          status: "failed",
          error: (e as Error).message,
          retry: () => {
            removeTransfer(transferId);
            convertBooks([book], mode);
          },
        });
      }
    }
  });
}
