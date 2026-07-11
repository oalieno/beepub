/**
 * SyncBackend answers "where does this user's reading state live":
 * progress and highlights. The BeePub server is one implementation; a
 * local store and third-party kosync servers arrive with later phases.
 */
import type { HighlightOut } from "$lib/types";

import type { Locator } from "./locator";

/** Position reported by another device (BeePub: bridged from kosync). */
export interface DevicePosition {
  /** 0..100 — the kosync wire convention, preserved as-is. */
  percentage: number | null;
  device: string | null;
  sectionIndex: number | null;
  /** Raw device xpointer for paragraph-level resolution, when available. */
  xpointer: string | null;
}

export interface ProgressState {
  /** null = nothing saved yet. */
  locator: Locator | null;
  fontSize: number | null;
  sectionIndex: number | null;
  sectionPage: number | null;
  sectionPageCounts: number[] | null;
  totalPages: number | null;
  lastReadAt: string | null;
  devicePosition: DevicePosition | null;
}

export interface ProgressSave {
  /** fragments[0] (the CFI) is required. totalProgression undefined means
   *  "canonical percentage unknown — keep the stored value". */
  locator: Locator;
  fontSize: number;
  sectionIndex: number;
  sectionPage: number;
  sectionPageCounts: number[];
  totalPages: number;
  /** crengine-style xpointer for the same position, when the reader could
   *  compute one — served to e-readers pulling through kosync so they land
   *  on the paragraph instead of the chapter start. */
  xpointer: string | null;
  trackActivity: boolean;
}

// Highlight payloads stay wire-shaped (HighlightOut + snake_case) for now:
// the value of this interface is the choke point, not type purity. A
// neutral shape lands when a second implementation (local store) exists.
export interface HighlightDraft {
  cfi_range: string;
  text: string;
  color: string;
  note?: string;
  prefix?: string | null;
  suffix?: string | null;
  section_index?: number | null;
}

export interface HighlightPatch {
  color?: string;
  note?: string;
  cfi_range?: string;
  section_index?: number;
}

export interface SyncBackend {
  readonly kind: "beepub" | "local" | "kosync";
  getProgress(bookId: string): Promise<ProgressState | null>;
  saveProgress(bookId: string, state: ProgressSave): Promise<void>;
  /** Fire-and-forget save for page unload (beepub: keepalive fetch). */
  saveProgressBeacon(bookId: string, state: ProgressSave): void;
  listHighlights(bookId: string): Promise<HighlightOut[]>;
  createHighlight(bookId: string, data: HighlightDraft): Promise<HighlightOut>;
  updateHighlight(
    bookId: string,
    highlightId: string,
    patch: HighlightPatch,
  ): Promise<HighlightOut>;
  deleteHighlight(bookId: string, highlightId: string): Promise<void>;
}
