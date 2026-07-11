/**
 * Internal reading-position type using Readium Locator field naming
 * (https://readium.org/architecture/models/locators/). It travels between
 * the reader and SyncBackend implementations; each backend maps it to its
 * own wire format (BeePub: cfi/percentage/current_page — untouched by this
 * abstraction; kosync later: xpointer/percentage).
 */
export interface Locator {
  /** Spine item href ("" when unknown — the BeePub wire doesn't carry it). */
  href: string;
  /** MIME type of the resource ("application/xhtml+xml" for EPUB sections). */
  type: string;
  title?: string;
  locations: {
    /** ["epubcfi(...)"] — the CFI travels as a fragment, per the Readium
     *  EPUB profile. */
    fragments?: string[];
    /** 0..1 within the resource. */
    progression?: number;
    /** Synthetic page number in the whole book (BeePub wire: current_page). */
    position?: number;
    /** 0..1 across the whole book. BeePub wire percentage (0..100) =
     *  totalProgression × 100. undefined = unknown, which BeePub maps to
     *  percentage: null ("keep the stored value"). */
    totalProgression?: number;
  };
  text?: {
    /** BeePub highlight wire: prefix. */
    before?: string;
    /** BeePub highlight wire: text. */
    highlight?: string;
    /** BeePub highlight wire: suffix. */
    after?: string;
  };
}

export function cfiOf(locator: Locator): string | null {
  const fragment = locator.locations.fragments?.[0];
  return fragment && fragment.startsWith("epubcfi(") ? fragment : null;
}

export function locatorFromCfi(
  cfi: string,
  locations: Omit<Locator["locations"], "fragments"> = {},
): Locator {
  return {
    href: "",
    type: "application/xhtml+xml",
    locations: { fragments: [cfi], ...locations },
  };
}
