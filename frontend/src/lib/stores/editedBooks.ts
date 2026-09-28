/**
 * Books edited this session (metadata, cover, TXT rebuild), as the server
 * returned them. List pages restored from a snapshot on back keep the
 * rows they fetched before the edit; cards lay the newer copy over them.
 */
import { writable } from "svelte/store";

import type { BookOut } from "$lib/types";

export const editedBooks = writable<ReadonlyMap<string, BookOut>>(new Map());

export function noteBookEdited<T extends BookOut>(book: T): T {
  editedBooks.update((m) => new Map(m).set(book.id, book));
  return book;
}

/** The row with any newer edit laid over it. Fields the edit response
 *  doesn't carry (inline reading status) stay the row's. */
export function withEdit<T extends BookOut>(
  book: T,
  edits: ReadonlyMap<string, BookOut>,
): T {
  const edit = edits.get(book.id);
  if (!edit || Date.parse(edit.updated_at) <= Date.parse(book.updated_at))
    return book;
  return { ...book, ...edit };
}
