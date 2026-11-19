// How a book is named on the bookshelf.
import type { BookOut } from "#lib/types.ts";

const authors = (b: BookOut) =>
  b.display_authors ?? b.authors ?? b.epub_authors ?? [];

export const titleOf = (b: BookOut) =>
  b.display_title ?? b.title ?? b.epub_title ?? "";
/** The one name there is room for on a spine. */
export const authorOf = (b: BookOut) => authors(b)[0] ?? "";
export const authorsOf = (b: BookOut) => authors(b).join("、");
