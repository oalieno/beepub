import { getLocale } from "$lib/paraglide/runtime.js";

const ACRONYMS = new Set(["ai", "bl", "cjk", "lgbtq", "rpg", "sf", "vr", "ya"]);

function titleCaseTag(tag: string): string {
  return tag
    .split(/([ -])/)
    .map((part) => {
      if (part === " " || part === "-") return part;
      const lower = part.toLowerCase();
      if (ACRONYMS.has(lower)) return lower.toUpperCase();
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join("");
}

/** The tag as the interface language shows it. `label` is the
 *  Traditional Chinese label, `labelHans` the Simplified one. */
export function localizedTagLabel(
  tag: string,
  label?: string | null,
  labelHans?: string | null,
): string {
  const locale = getLocale();
  if (locale === "zh-Hans") return labelHans || label || tag;
  if (locale === "zh-Hant") return label || tag;
  return titleCaseTag(tag);
}
