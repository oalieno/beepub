/**
 * The section a stored highlight's CFI points into, for highlights saved
 * without their section index. Verifying and healing anchors against the
 * book is the reader's own (lib/reader/anchor.ts).
 */

/** Spine index encoded in an EPUB CFI (`/6/<2*(index+1)>!/...`). */
export function sectionIndexFromCfi(cfi: string): number | null {
  const match = /^epubcfi\(\/6\/(\d+)/.exec(cfi);
  if (!match) return null;
  const step = parseInt(match[1], 10);
  return step >= 2 && step % 2 === 0 ? step / 2 - 1 : null;
}
