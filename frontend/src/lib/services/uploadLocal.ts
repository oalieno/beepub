/**
 * Moving a book from the local library into a server library. Upload has
 * no digest dedup (a re-upload mints a duplicate book), so a book whose
 * file is already on the server is linked instead — either way the copy
 * then syncs its reading state with the server book.
 */
import { booksApi } from "$lib/api/books";
import { sanitizeFilename } from "$lib/services/epubDownload";
import {
  getLocalBookLinks,
  listLocalBooks,
  readLocalBookBytes,
  setLocalBookLink,
  type LocalBookEntry,
} from "$lib/services/localLibrary";
import { refreshLinkedBookIds } from "$lib/stores/linkedBooks";

/** Local books not yet on the server, newest import first. */
export async function unlinkedLocalBooks(): Promise<LocalBookEntry[]> {
  const [entries, links] = await Promise.all([
    listLocalBooks(),
    getLocalBookLinks(),
  ]);
  return entries
    .filter((e) => !links[e.id])
    .sort((a, b) => b.importedAt.localeCompare(a.importedAt));
}

export async function uploadLocalBook(
  entry: LocalBookEntry,
  libraryId: string,
): Promise<"uploaded" | "linked"> {
  const { matches } = await booksApi.lookupByDigest([entry.digest]);
  const match = matches[entry.digest];
  let outcome: "uploaded" | "linked" = "linked";
  let serverId = match?.id;
  if (!serverId) {
    const bytes = await readLocalBookBytes(entry.id);
    if (!bytes) throw new Error(`Local book file missing: ${entry.id}`);
    const file = new File([bytes], `${sanitizeFilename(entry.title)}.epub`, {
      type: "application/epub+zip",
    });
    serverId = (await booksApi.upload(file, libraryId)).id;
    outcome = "uploaded";
  }
  await setLocalBookLink(entry.id, serverId);
  void refreshLinkedBookIds();
  // Ship the accumulated reading state to the server book.
  void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
    syncLocalBook(entry.id).catch(() => {}),
  );
  return outcome;
}
