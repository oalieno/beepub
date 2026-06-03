import type { TierBand } from "$lib/types";

// A tier preset is an ordered list of bands. `min` is the inclusive lower
// bound of the band on the 0.5-5 rating scale; a rating belongs to the
// highest band whose `min` it meets. Bands are stored highest-first.
export interface TierPreset {
  key: string;
  name: string;
  bands: TierBand[];
  chineseOnly?: boolean; // only offered when the UI locale is Chinese
}

// Hot (top) -> cold (bottom) colour ramp, 10 stops.
const RAMP = [
  "#ff4757",
  "#ff6348",
  "#ff7f50",
  "#ff9f43",
  "#ffa502",
  "#f6c343",
  "#c5d92e",
  "#7bed9f",
  "#70a1ff",
  "#a4b0be",
];

// Build bands from [min, label] pairs (highest-first), spreading colours
// evenly along the ramp so 5-band and 10-band presets both look graded.
function bands(pairs: [number, string][]): TierBand[] {
  const n = pairs.length;
  return pairs.map(([min, label], i) => ({
    min,
    label,
    color: RAMP[n === 1 ? 0 : Math.round((i / (n - 1)) * (RAMP.length - 1))],
  }));
}

export const TIER_PRESETS: TierPreset[] = [
  {
    key: "gacha",
    name: "UR / SSR / SR",
    bands: bands([
      [5, "UR"],
      [4, "SSR"],
      [3, "SR"],
      [2, "R"],
      [0.5, "N"],
    ]),
  },
  {
    key: "gacha_fine",
    name: "UR / SSR+ / SSR",
    bands: bands([
      [5, "UR"],
      [4.5, "SSR+"],
      [4, "SSR"],
      [3.5, "SR+"],
      [3, "SR"],
      [2.5, "R+"],
      [2, "R"],
      [1.5, "N+"],
      [1, "N"],
      [0.5, "N-"],
    ]),
  },
  {
    key: "rank",
    name: "S / A+ / B",
    bands: bands([
      [5, "S"],
      [4.5, "A+"],
      [4, "A"],
      [3.5, "B+"],
      [3, "B"],
      [2.5, "C+"],
      [2, "C"],
      [1.5, "D+"],
      [1, "D"],
      [0.5, "E"],
    ]),
  },
  {
    key: "meme",
    name: "夯 / 頂級 / 拉完了",
    chineseOnly: true,
    bands: bands([
      [5, "夯"],
      [4, "頂級"],
      [3, "人上人"],
      [2, "NPC"],
      [0.5, "拉完了"],
    ]),
  },
];

export const DEFAULT_PRESET_KEY = "gacha";

export function defaultBands(): TierBand[] {
  return (
    TIER_PRESETS.find((p) => p.key === DEFAULT_PRESET_KEY) ?? TIER_PRESETS[0]
  ).bands;
}

// Resolve the active bands for a user: their custom theme, or the default
// preset. Always returned sorted highest-first so tier rows render top-down.
export function resolveBands(
  userTheme: TierBand[] | null | undefined,
): TierBand[] {
  const bands = userTheme && userTheme.length > 0 ? userTheme : defaultBands();
  return [...bands].sort((a, b) => b.min - a.min);
}

// The tier a given rating falls into (highest band whose min it meets).
export function tierFor(rating: number, bands: TierBand[]): TierBand | null {
  for (const band of bands) {
    if (rating >= band.min) return band;
  }
  return null;
}
