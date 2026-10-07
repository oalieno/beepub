/**
 * Weight-interpolated reading progress.
 *
 * Position (the CFI) stays precise; the displayed percentage only needs to
 * be stable, monotone and always available. It is interpolated from
 * per-spine-section text sizes: the weight of everything before the current
 * section plus the in-section fraction of the current one, over the total.
 * No generation step, no cache, and every device computes the same number
 * from the same book.
 *
 * Books without weights (extraction pending, sideloads not yet counted,
 * image-only books) fall back to uniform section weights — cruder, but
 * still monotone, and exact for one-image-per-section books.
 */

/** Dense, non-negative weights sized to the spine. All-zero (or missing)
 *  input degrades to uniform weights so the math below never divides by
 *  zero and image books get section-based progress for free. */
export function usableWeights(
  weights: readonly number[] | null | undefined,
  sectionCount: number,
): number[] {
  if (sectionCount <= 0) return [];
  const out = new Array<number>(sectionCount).fill(0);
  let sum = 0;
  if (Array.isArray(weights)) {
    const n = Math.min(weights.length, sectionCount);
    for (let i = 0; i < n; i++) {
      const w = weights[i];
      if (typeof w === "number" && Number.isFinite(w) && w > 0) {
        out[i] = w;
        sum += w;
      }
    }
  }
  if (sum === 0) out.fill(1);
  return out;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** 0..100 (unrounded). `fractionInSection` is how far through the current
 *  section the reader sits, e.g. completed pages over the section's pages. */
export function percentFromPosition(
  weights: readonly number[],
  sectionIndex: number,
  fractionInSection: number,
): number {
  if (weights.length === 0) return 0;
  // A position that is not one (no section, no fraction) is the start of
  // the book: the result is always a number.
  const at = Number.isFinite(sectionIndex) ? Math.trunc(sectionIndex) : 0;
  const fraction = Number.isFinite(fractionInSection) ? fractionInSection : 0;
  let total = 0;
  let before = 0;
  for (let i = 0; i < weights.length; i++) {
    total += weights[i]!;
    if (i < at) before += weights[i]!;
  }
  if (!(total > 0)) return 0;
  const index = Math.min(weights.length - 1, Math.max(0, at));
  const within = clamp01(fraction) * weights[index]!;
  const percent = ((before + within) / total) * 100;
  return Number.isFinite(percent) ? Math.min(100, Math.max(0, percent)) : 0;
}

/** The inverse: which section (and how far into it) a percentage lands on.
 *  Zero-weight sections are never chosen — a seek can't land on a slot the
 *  forward mapping can't leave. */
export function positionFromPercent(
  weights: readonly number[],
  percentage: number,
): { sectionIndex: number; fraction: number } {
  if (weights.length === 0) return { sectionIndex: 0, fraction: 0 };
  let total = 0;
  for (const w of weights) total += w;
  if (total <= 0) return { sectionIndex: 0, fraction: 0 };

  const target = clamp01(percentage / 100) * total;
  let cumulative = 0;
  let lastWeighted = 0;
  for (let i = 0; i < weights.length; i++) {
    const w = weights[i]!;
    if (w <= 0) continue;
    lastWeighted = i;
    if (target < cumulative + w) {
      return { sectionIndex: i, fraction: (target - cumulative) / w };
    }
    cumulative += w;
  }
  // target === total (the 100% case) falls out of the loop.
  return { sectionIndex: lastWeighted, fraction: 1 };
}

/** A tick per spine section works for prose (one file per chapter); a
 *  comic's one-image-per-section spine would paint a picket fence, so
 *  past this count the scrubber goes tickless. */
export const MAX_SCRUBBER_TICKS = 40;

/** Section-start positions (percent) on the weight scale — the same scale
 *  the scrubber seeks on. Zero-weight sections are skipped: their start
 *  coincides with the next weighted one. [] past MAX_SCRUBBER_TICKS. */
export function sectionTickPercents(weights: readonly number[]): number[] {
  let total = 0;
  for (const w of weights) total += w;
  if (total <= 0) return [];
  const out: number[] = [];
  let before = 0;
  for (let i = 0; i < weights.length; i++) {
    if (i > 0 && weights[i]! > 0) {
      const pct = (before / total) * 100;
      if (pct > 0.5 && pct < 99.5) out.push(pct);
    }
    before += weights[i]!;
  }
  return out.length > MAX_SCRUBBER_TICKS ? [] : out;
}

/** A section's page count as it is stored and sent: a whole number, 0 for
 *  a section that has not been laid out. Dense — a sparse array (a jump
 *  leaves holes for the sections it skipped) and a NaN both become null
 *  in JSON, which a server refuses, and a record once written that way is
 *  sent again unchanged by every sync. Every writer and every reader of a
 *  progress record passes its counts through here. */
export function densePageCounts(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return Array.from({ length: value.length }, (_, index) => {
    const count: unknown = value[index];
    return typeof count === "number" && Number.isFinite(count) && count > 0
      ? Math.round(count)
      : 0;
  });
}
