/**
 * Highlight anchor verification and healing.
 *
 * A highlight's cfi_range stops resolving when the book file is rewritten
 * (calibre metadata edit, re-conversion, re-split). Instead of letting the
 * annotation silently vanish, verify each stored CFI against the actual
 * section DOM and re-anchor by quote search (W3C TextQuoteSelector spirit:
 * the text plus stored prefix/suffix context) — first in the highlight's
 * own section, then across the whole spine. Anything that can't be
 * relocated unambiguously is reported broken so the UI can say so; a
 * guessed anchor would silently move the user's highlight, which is worse.
 */
import type { HighlightOut } from "$lib/types";

export interface HealedAnchor {
  id: string;
  oldCfi: string;
  cfi: string;
  sectionIndex: number;
}

export interface AnchorReport {
  healed: HealedAnchor[];
  broken: string[];
}

const normalize = (s: string) => s.replace(/[\s\u00a0]+/g, " ").trim();

/** Spine index encoded in an epub.js CFI (`/6/<2*(index+1)>!/...`). */
export function sectionIndexFromCfi(cfi: string): number | null {
  const match = /^epubcfi\(\/6\/(\d+)/.exec(cfi);
  if (!match) return null;
  const step = parseInt(match[1], 10);
  return step >= 2 && step % 2 === 0 ? step / 2 - 1 : null;
}

function cfiResolvesToText(
  EpubCFI: any,
  cfi: string,
  doc: Document,
  text: string,
): boolean {
  try {
    const range = new EpubCFI(cfi).toRange(doc);
    return !!range && normalize(range.toString()) === normalize(text);
  } catch {
    return false;
  }
}

/**
 * Locate the quote in a loaded section. Returns a CFI only when the match
 * is unambiguous: a single occurrence, or several where the stored
 * prefix/suffix context singles one out.
 */
function findQuote(
  section: any,
  h: Pick<HighlightOut, "text" | "prefix" | "suffix">,
): string | null {
  let matches: { cfi: string; excerpt: string }[] = [];
  try {
    matches = section.find(h.text) ?? [];
  } catch {
    // fall through to search()
  }
  if (!matches.length) {
    try {
      // find() only sees single text nodes; search() spans up to 5
      // sequential elements (multi-paragraph selections).
      matches = section.search(h.text) ?? [];
    } catch {
      return null;
    }
  }
  if (!matches.length) return null;
  if (matches.length === 1) return matches[0].cfi;

  const prefixTail = normalize(h.prefix ?? "")
    .slice(-20)
    .toLowerCase();
  const suffixHead = normalize(h.suffix ?? "")
    .slice(0, 20)
    .toLowerCase();
  let top = 0;
  const scored = matches.map((match) => {
    const excerpt = normalize(match.excerpt).toLowerCase();
    let score = 0;
    if (prefixTail && excerpt.includes(prefixTail)) score += 1;
    if (suffixHead && excerpt.includes(suffixHead)) score += 1;
    top = Math.max(top, score);
    return { match, score };
  });
  const best = scored.filter((s) => s.score === top);
  return top > 0 && best.length === 1 ? best[0].match.cfi : null;
}

/**
 * Verify every highlight's anchor against the book and heal the ones that
 * moved. Best-effort and read-only: the caller applies the report (update
 * annotations, persist new CFIs, surface the broken ones).
 */
export async function verifyHighlightAnchors(
  book: any,
  highlights: HighlightOut[],
): Promise<AnchorReport> {
  const EpubCFI = (await import("$lib/epubjs/epubcfi")).default;
  const healed: HealedAnchor[] = [];
  const broken: string[] = [];
  const spineLength = book?.spine?.spineItems?.length ?? 0;
  const sections = new Map<number, any | null>();

  const loadedSection = async (index: number) => {
    if (sections.has(index)) return sections.get(index);
    let section = null;
    try {
      section = book.spine?.get(index) ?? null;
      if (section) await section.load(book.load.bind(book));
    } catch {
      section = null;
    }
    sections.set(index, section);
    return section;
  };

  for (const h of highlights) {
    const home = h.section_index ?? sectionIndexFromCfi(h.cfi_range);
    let homeSection = null;
    if (home != null) {
      homeSection = await loadedSection(home);
      if (
        homeSection &&
        cfiResolvesToText(EpubCFI, h.cfi_range, homeSection.document, h.text)
      ) {
        continue; // anchor intact
      }
      if (homeSection) {
        const cfi = findQuote(homeSection, h);
        if (cfi) {
          healed.push({
            id: h.id,
            oldCfi: h.cfi_range,
            cfi,
            sectionIndex: home,
          });
          continue;
        }
      }
    }
    // The quote left its section (file re-split) — sweep the whole spine.
    let found = false;
    for (let i = 0; i < spineLength && !found; i++) {
      if (i === home) continue;
      const section = await loadedSection(i);
      if (!section) continue;
      const cfi = findQuote(section, h);
      if (cfi) {
        healed.push({ id: h.id, oldCfi: h.cfi_range, cfi, sectionIndex: i });
        found = true;
      }
    }
    if (!found) broken.push(h.id);
  }

  return { healed, broken };
}
