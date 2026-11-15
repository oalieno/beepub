/**
 * How a date and a file's size are written, in one place.
 *
 * Dates are written in the language BeePub is set to — not the
 * browser's, which can differ (an English browser, the app in Chinese).
 */
import { getLocale } from "$lib/paraglide/runtime.js";

const DATE_STYLES = {
  /** "Nov 15" — where the year would be noise (a list of recent marks). */
  day: { month: "short", day: "numeric" },
  /** "Nov 15, 2026" */
  date: { month: "short", day: "numeric", year: "numeric" },
  /** "11/15/2026" — a column of dates. */
  numeric: { year: "numeric", month: "numeric", day: "numeric" },
  /** "Nov 15, 02:30 PM" — when the hour tells two apart. */
  minute: {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  },
} satisfies Record<string, Intl.DateTimeFormatOptions>;

export type DateStyle = keyof typeof DATE_STYLES;

/** An ISO time as a date. What cannot be read as one is written as
 *  nothing, never as "Invalid Date". */
export function formatDate(
  iso: string | null | undefined,
  style: DateStyle = "date",
  locale: string = getLocale(),
): string {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  return new Intl.DateTimeFormat(locale, DATE_STYLES[style]).format(when);
}

const KB = 1024;
const MB = KB * 1024;
const GB = MB * 1024;

/** A size in the unit a person would say it in: "812 KB", "3.4 MB",
 *  "1.2 GB". */
export function formatSize(bytes: number): string {
  if (bytes < MB) return `${Math.round(bytes / KB)} KB`;
  if (bytes < GB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${(bytes / GB).toFixed(1)} GB`;
}
