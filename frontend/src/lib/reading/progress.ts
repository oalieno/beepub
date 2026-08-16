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
  let total = 0;
  let before = 0;
  for (let i = 0; i < weights.length; i++) {
    total += weights[i]!;
    if (i < sectionIndex) before += weights[i]!;
  }
  if (total <= 0) return 0;
  const index = Math.min(weights.length - 1, Math.max(0, sectionIndex));
  const within = clamp01(fractionInSection) * weights[index]!;
  return Math.min(100, Math.max(0, ((before + within) / total) * 100));
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
