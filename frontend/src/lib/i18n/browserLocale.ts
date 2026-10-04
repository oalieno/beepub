/**
 * The interface language for a visitor who hasn't picked one: the first
 * of the browser's languages we have. Paraglide's own preferredLanguage
 * strategy only matches tags exactly (or by bare language), so "zh-TW"
 * would never find "zh-Hant".
 */
export type AppLocale = "en" | "zh-Hant" | "zh-Hans";

/** Paraglide strategy name (vite.config.ts lists it before baseLocale). */
export const BROWSER_LOCALE_STRATEGY = "custom-browser";

function match(tag: string): AppLocale | undefined {
  const parts = tag.trim().toLowerCase().split("-");
  if (parts[0] === "en") return "en";
  if (parts[0] !== "zh") return undefined;
  if (parts.includes("hant")) return "zh-Hant";
  if (parts.includes("hans")) return "zh-Hans";
  // No script given: the region decides. Bare "zh" reads as Simplified.
  return parts.some((p) => p === "tw" || p === "hk" || p === "mo")
    ? "zh-Hant"
    : "zh-Hans";
}

/** `tags` in preference order, as navigator.languages gives them. */
export function localeFromLanguages(
  tags: readonly string[],
): AppLocale | undefined {
  for (const tag of tags) {
    const locale = match(tag);
    if (locale) return locale;
  }
  return undefined;
}

/** An Accept-Language header, sorted by its q weights. */
export function localeFromAcceptLanguage(
  header: string | null,
): AppLocale | undefined {
  if (!header) return undefined;
  const tags = header
    .split(",")
    .map((item, i) => {
      const [tag, ...params] = item.split(";");
      const q = params.find((p) => p.trim().startsWith("q="));
      return { tag, q: q ? Number(q.trim().slice(2)) || 0 : 1, i };
    })
    .sort((a, b) => b.q - a.q || a.i - b.i)
    .map((item) => item.tag);
  return localeFromLanguages(tags);
}
