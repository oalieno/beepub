/**
 * Highlight color + style handling.
 *
 * The style (highlight / underline / squiggly) is encoded into the existing
 * `color` string field as "yellow:underline" — the column is a free-form
 * String(20) and every sync path (server API, device sync, local manifests)
 * already carries it opaquely, so no backend or sync changes are needed.
 * Old clients that don't know the suffix fall back to a yellow highlight
 * (their palette lookup misses), which degrades gracefully.
 */

export type HighlightStyle = "highlight" | "underline" | "squiggly";

export const HIGHLIGHT_STYLES: HighlightStyle[] = [
  "highlight",
  "underline",
  "squiggly",
];

export const HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "#fef08a",
  green: "#bbf7d0",
  blue: "#bfdbfe",
  pink: "#fbcfe8",
  orange: "#fed7aa",
};

/** Saturated variants for line styles — the pastel fill tints are too
 *  faint to read as a 2px line. */
export const HIGHLIGHT_LINE_COLORS: Record<string, string> = {
  yellow: "#eab308",
  green: "#22c55e",
  blue: "#3b82f6",
  pink: "#ec4899",
  orange: "#f97316",
};

export function parseHighlightColor(raw: string): {
  color: string;
  style: HighlightStyle;
} {
  const [color, style] = raw.split(":");
  return {
    color: color in HIGHLIGHT_COLORS ? color : "yellow",
    style: style === "underline" || style === "squiggly" ? style : "highlight",
  };
}

export function encodeHighlightColor(
  color: string,
  style: HighlightStyle,
): string {
  return style === "highlight" ? color : `${color}:${style}`;
}
