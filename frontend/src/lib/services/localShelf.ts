/**
 * The device shelf as the pages show it: manifest entries plus their
 * per-mount cover URIs, link state and reading records. Shared by the
 * shelf page and Home (both modes), which is where the continue-reading
 * row lives.
 */
import type { LocalShelfEntry } from "$lib/components/LocalBookCard.svelte";
import type { ContinueReadingItem } from "$lib/components/ContinueReadingRow.svelte";
import { isNative } from "$lib/platform";
import { readLocalInteraction, readLocalProgress } from "$lib/reading/local";
import {
  getLocalBookLinks,
  getLocalCoverSrc,
  listLocalBooks,
  type LocalBookEntry,
} from "$lib/services/localLibrary";

/** Cover URIs are re-derived per mount, so they ride beside the entry
 *  instead of living in the manifest. */
export async function toShelfEntry(
  entry: LocalBookEntry,
  links: Record<string, string>,
): Promise<LocalShelfEntry> {
  const [coverSrc, progress, interaction] = await Promise.all([
    getLocalCoverSrc(entry),
    readLocalProgress(entry.id),
    readLocalInteraction(entry.id),
  ]);
  return {
    ...entry,
    coverSrc,
    linked: entry.id in links,
    progressPct: progress?.percentage ?? null,
    readingStatus: interaction?.reading_status ?? null,
    lastReadAt: progress?.last_read_at ?? null,
  };
}

/** Every book on the device (empty off-device). */
export async function loadShelfEntries(): Promise<LocalShelfEntry[]> {
  if (!isNative()) return [];
  const [books, links] = await Promise.all([
    listLocalBooks(),
    getLocalBookLinks(),
  ]);
  return Promise.all(books.map((b) => toShelfEntry(b, links)));
}

export type LocalContinueItem = ContinueReadingItem & { lastReadAt: string };

/** Books started and not finished, most recently read first. */
export function continueItems(entries: LocalShelfEntry[]): LocalContinueItem[] {
  return entries
    .filter(
      (e) =>
        e.lastReadAt &&
        e.readingStatus !== "read" &&
        e.readingStatus !== "did_not_finish",
    )
    .sort((a, b) => b.lastReadAt!.localeCompare(a.lastReadAt!))
    .map((e) => ({
      id: e.id,
      title: e.title,
      authors: e.authors,
      percentage: e.progressPct ?? null,
      coverSrc: e.coverSrc,
      lastReadAt: e.lastReadAt!,
    }));
}
