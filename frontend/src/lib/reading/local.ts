/**
 * Local implementations of BookSource and SyncBackend. Reading state for
 * device-local books lives in Capacitor Preferences, wire-shaped to mirror
 * the server records — the mapping code stays a twin of beepub.ts, and a
 * future sync can diff the two stores without translation. Records carry
 * updated_at (and highlights a deleted_at tombstone) so they can LWW-merge
 * with the server later.
 */
import { Preferences } from "@capacitor/preferences";

import {
  localHighlightsKey,
  localProgressKey,
  readLocalBookBytes,
} from "$lib/services/localLibrary";
import type { HighlightOut } from "$lib/types";

import { cfiOf, locatorFromCfi } from "./locator";
import type { BookPayload, BookSource } from "./source";
import type {
  HighlightDraft,
  HighlightPatch,
  ProgressSave,
  ProgressState,
  SyncBackend,
} from "./sync";

class LocalBookSource implements BookSource {
  readonly kind = "local" as const;

  // No shared-locations capability: the reader generates locations itself
  // and keeps them in the IndexedDB cache.
  async openBook(bookId: string): Promise<BookPayload> {
    const data = await readLocalBookBytes(bookId);
    if (!data) throw new Error(`Local book file missing: ${bookId}`);
    return { kind: "bytes", data };
  }
}

/** Stored progress — the server wire dict plus updated_at (the LWW field
 *  the sync engine compares against the server's). */
export interface LocalProgressRecord {
  cfi: string;
  percentage: number | null;
  current_page: number;
  font_size: number;
  section_index: number;
  section_page: number;
  section_page_counts: number[];
  total_pages: number;
  xpointer: string | null;
  last_read_at: string;
  updated_at: string;
  /** E-reader position pulled through sync (the server's kosync marker).
   *  saveProgress rewrites the record without it — the first local move
   *  consumes the marker, mirroring the server's rebuild semantics. */
  kosync?: {
    percentage: number | null;
    device: string | null;
    synced_at: string | null;
    section_index: number | null;
    xpointer: string | null;
  } | null;
}

export type LocalHighlightRecord = HighlightOut & {
  deleted_at: string | null;
};

async function readJson<T>(key: string): Promise<T | null> {
  const { value } = await Preferences.get({ key });
  if (!value) return null;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}

async function writeJson(key: string, value: unknown): Promise<void> {
  await Preferences.set({ key, value: JSON.stringify(value) });
}

// Storage accessors for the sync engine (services/readingSync.ts) — it
// merges server state into the same records this backend reads.
export async function readLocalProgress(
  bookId: string,
): Promise<LocalProgressRecord | null> {
  return readJson<LocalProgressRecord>(localProgressKey(bookId));
}

export async function writeLocalProgress(
  bookId: string,
  record: LocalProgressRecord,
): Promise<void> {
  await writeJson(localProgressKey(bookId), record);
}

export async function readLocalHighlightRecords(
  bookId: string,
): Promise<LocalHighlightRecord[]> {
  return (
    (await readJson<LocalHighlightRecord[]>(localHighlightsKey(bookId))) ?? []
  );
}

export async function writeLocalHighlightRecords(
  bookId: string,
  records: LocalHighlightRecord[],
): Promise<void> {
  await writeJson(localHighlightsKey(bookId), records);
}

class LocalSyncBackend implements SyncBackend {
  readonly kind = "local" as const;

  async getProgress(bookId: string): Promise<ProgressState | null> {
    const p = await readJson<LocalProgressRecord>(localProgressKey(bookId));
    if (!p) return null;
    return {
      locator: p.cfi
        ? locatorFromCfi(p.cfi, {
            totalProgression:
              p.percentage == null ? undefined : p.percentage / 100,
            position: p.current_page ?? undefined,
          })
        : null,
      fontSize: p.font_size,
      sectionIndex: p.section_index,
      sectionPage: p.section_page,
      sectionPageCounts: p.section_page_counts,
      totalPages: p.total_pages,
      lastReadAt: p.last_read_at,
      devicePosition: p.kosync
        ? {
            percentage: p.kosync.percentage,
            device: p.kosync.device,
            sectionIndex: p.kosync.section_index ?? null,
            xpointer: p.kosync.xpointer ?? null,
          }
        : null,
    };
  }

  async saveProgress(bookId: string, state: ProgressSave): Promise<void> {
    const key = localProgressKey(bookId);
    const existing = await readJson<LocalProgressRecord>(key);
    const totalProgression = state.locator.locations.totalProgression;
    const now = new Date().toISOString();
    const record: LocalProgressRecord = {
      cfi: cfiOf(state.locator) ?? "",
      // Same contract as the wire: undefined totalProgression means the
      // canonical percentage is unknown (locations not ready yet) — keep
      // the stored value rather than clobbering it.
      percentage:
        totalProgression === undefined
          ? (existing?.percentage ?? null)
          : totalProgression * 100,
      current_page: state.locator.locations.position ?? 0,
      font_size: state.fontSize,
      section_index: state.sectionIndex,
      section_page: state.sectionPage,
      section_page_counts: state.sectionPageCounts,
      total_pages: state.totalPages,
      xpointer: state.xpointer,
      last_read_at: now,
      updated_at: now,
    };
    await writeJson(key, record);
  }

  saveProgressBeacon(bookId: string, state: ProgressSave): void {
    // A Preferences write can be lost if the WebView dies mid-bridge-call.
    // Acceptable: saveProgress already ran on every relocation behind a 2s
    // debounce, so at most a few seconds of position are at stake.
    void this.saveProgress(bookId, state).catch(() => {});
  }

  private async readHighlights(
    bookId: string,
  ): Promise<LocalHighlightRecord[]> {
    return (
      (await readJson<LocalHighlightRecord[]>(localHighlightsKey(bookId))) ?? []
    );
  }

  async listHighlights(bookId: string): Promise<HighlightOut[]> {
    const all = await this.readHighlights(bookId);
    return all.filter((h) => h.deleted_at === null);
  }

  async createHighlight(
    bookId: string,
    data: HighlightDraft,
  ): Promise<HighlightOut> {
    const all = await this.readHighlights(bookId);
    const now = new Date().toISOString();
    const record: LocalHighlightRecord = {
      id: crypto.randomUUID(),
      book_id: bookId,
      user_id: "local",
      cfi_range: data.cfi_range,
      text: data.text,
      color: data.color,
      note: data.note ?? null,
      prefix: data.prefix ?? null,
      suffix: data.suffix ?? null,
      section_index: data.section_index ?? null,
      created_at: now,
      updated_at: now,
      deleted_at: null,
    };
    all.push(record);
    await writeJson(localHighlightsKey(bookId), all);
    return record;
  }

  async updateHighlight(
    bookId: string,
    highlightId: string,
    patch: HighlightPatch,
  ): Promise<HighlightOut> {
    const all = await this.readHighlights(bookId);
    const record = all.find(
      (h) => h.id === highlightId && h.deleted_at === null,
    );
    // Tombstoned counts as gone — the server answers 404 here, and callers
    // like the healing writeback already swallow the failure.
    if (!record) throw new Error("Highlight not found");
    if (patch.color !== undefined) record.color = patch.color;
    if (patch.note !== undefined) record.note = patch.note;
    if (patch.cfi_range !== undefined) record.cfi_range = patch.cfi_range;
    if (patch.section_index !== undefined)
      record.section_index = patch.section_index;
    record.updated_at = new Date().toISOString();
    await writeJson(localHighlightsKey(bookId), all);
    return record;
  }

  async deleteHighlight(bookId: string, highlightId: string): Promise<void> {
    const all = await this.readHighlights(bookId);
    const record = all.find((h) => h.id === highlightId);
    // Tombstone, not removal — deletions must be able to propagate once
    // sync exists. Re-deleting is a silent no-op (server semantics).
    if (record && record.deleted_at === null) {
      const now = new Date().toISOString();
      record.deleted_at = now;
      record.updated_at = now;
      await writeJson(localHighlightsKey(bookId), all);
    }
  }
}

export const localSource: BookSource = new LocalBookSource();
export const localSync: SyncBackend = new LocalSyncBackend();
