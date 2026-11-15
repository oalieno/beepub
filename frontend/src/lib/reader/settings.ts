/**
 * The reader's display settings, as this device keeps them.
 *
 * They live in localStorage under the `reader-*` keys — per device, not
 * per account: a phone and a desk want different type. Two are kept per
 * book (the key suffixed with the book's id), because they are facts
 * about that book rather than tastes.
 *
 * What is read here was written by every version of the reader there
 * has been, so reading is forgiving: an old vocabulary is understood
 * (and rewritten), a value that makes no sense falls back to the
 * default. A query parameter, where one exists, wins over what is
 * stored — tests and deep links use that to stand on fixed ground.
 */
import type { PageTurnMode, WritingMode } from "./core";
import { DEFAULT_READER_FONT, readerFont, type ReaderFont } from "./fonts";
import type { PagerDirection, PagerMode, PagerTurn } from "./pages";

export const KEY = {
  font: "reader-font",
  size: "reader-size",
  lineHeight: "reader-lineheight",
  letterSpacing: "reader-letter-spacing",
  marginX: "reader-margin-x",
  marginY: "reader-margin-y",
  /** The epub.js reader's single inline-padding preset; seeds both
   *  gutters when the split keys are absent. */
  legacyMargin: "reader-margin",
  pageTurn: "reader-page-turn",
  fullPage: "reader-full-page",
  dark: "reader-dark",
  pagerMode: "reader-pager-mode",
  pagerDirection: "reader-pager-direction",
  /** The image pager's own page turn (instant / curl): a comic's turn
   *  is chosen apart from a text book's. */
  pagerTurn: "reader-pager-turn",
  pagerPadding: "reader-pager-padding",
  /** Per book (suffixed with the id): whether its pairs are staggered
   *  is a fact about the file, not a preference. */
  pagerShift: "reader-pager-shift",
  /** Per book (suffixed with the id): horizontal or vertical is chosen
   *  for one book, not for every book the reader opens. */
  writingMode: "reader-writing-mode",
} as const;

export const FONT_SIZE_MIN = 10;
export const FONT_SIZE_MAX = 48;

export function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // private browsing
  }
}
export function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private browsing — the setting holds for this session */
  }
}
function forget(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* private browsing */
  }
}

function storedNum(key: string): number | null {
  const raw = stored(key);
  if (raw == null) return null;
  const v = Number(raw);
  return Number.isFinite(v) ? v : null;
}

export interface ReaderSettings {
  font: ReaderFont;
  fontSize: number;
  lineHeight: number;
  letterSpacing: number;
  marginX: number;
  marginY: number;
  fullPage: boolean;
  pageTurn: PageTurnMode;
  dark: boolean;
  pagerMode: PagerMode;
  pagerDirection: PagerDirection;
  pagerTurn: PagerTurn;
  pagerPadding: number;
}

/** What a reader who has never set anything gets (and what the server
 *  renders, where there is no device to ask). */
export const DEFAULT_SETTINGS: ReaderSettings = {
  font: DEFAULT_READER_FONT,
  fontSize: 16,
  lineHeight: 1.8,
  letterSpacing: 0,
  marginX: 32,
  marginY: 32,
  fullPage: false,
  pageTurn: "fade",
  dark: false,
  pagerMode: "single",
  pagerDirection: "auto",
  pagerTurn: "instant",
  pagerPadding: 0,
};

/** What a stored or query value means today: before 2026-10 the modes
 *  were instant / animated (a slide without the finger) / follow. */
export function parsePageTurn(
  raw: string | null,
): "fade" | "slide" | "curl" | "scroll" {
  if (raw === "scroll") return "scroll";
  if (raw === "curl") return "curl";
  return raw === "slide" || raw === "animated" || raw === "follow"
    ? "slide"
    : "fade";
}

export interface Device {
  /** Whether this device can draw the page curl. */
  canCurl: boolean;
  /** Whether the app around the reader is in its dark theme — the
   *  reader's own until the reader is given one. */
  appDark: boolean;
}

/** The settings to open the reader with. */
export function readSettings(
  query: URLSearchParams,
  device: Device,
): ReaderSettings {
  const d = DEFAULT_SETTINGS;

  function num(queryKey: string, keys: string[], fallback: number): number {
    if (query.has(queryKey)) {
      const v = Number(query.get(queryKey));
      if (Number.isFinite(v)) return v;
    }
    for (const key of keys) {
      const v = storedNum(key);
      if (v != null) return v;
    }
    return fallback;
  }
  /** A curl chosen on a phone is kept, though a desktop slides instead. */
  const curlHere = <T extends string>(mode: T): T | "slide" =>
    mode === "curl" && !device.canCurl ? "slide" : mode;

  function font(): ReaderFont {
    // (The query's two are the device's own fonts: a test's fixed
    // ground, whatever typeface the app serves.)
    const fromQuery = query.get("font");
    if (fromQuery === "sans") return "system";
    if (fromQuery === "serif") return "system-serif";
    return readerFont(fromQuery || stored(KEY.font));
  }
  function pageTurn(): PageTurnMode {
    const fromQuery = query.get("turn");
    if (fromQuery === "instant") return "instant";
    if (fromQuery) return curlHere(parsePageTurn(fromQuery));
    // Values from before there were two modes are read as today's and
    // rewritten, so the key holds one vocabulary.
    const raw = stored(KEY.pageTurn);
    if (raw === "curl") return curlHere("curl");
    const mode = parsePageTurn(raw);
    if (raw != null && raw !== mode) store(KEY.pageTurn, mode);
    return mode;
  }
  function dark(): boolean {
    if (query.has("dark")) return query.get("dark") === "1";
    const saved = stored(KEY.dark);
    return saved !== null ? saved === "1" : device.appDark;
  }
  function pagerMode(): PagerMode {
    const v = stored(KEY.pagerMode);
    return v === "double" ||
      v === "vertical" ||
      v === "horizontal" ||
      v === "webtoon"
      ? v
      : d.pagerMode;
  }
  function pagerDirection(): PagerDirection {
    const v = stored(KEY.pagerDirection);
    return v === "ltr" || v === "rtl" ? v : d.pagerDirection;
  }

  return {
    font: font(),
    fontSize: num("size", [KEY.size], d.fontSize),
    lineHeight: num("lh", [KEY.lineHeight], d.lineHeight),
    letterSpacing: num("ls", [KEY.letterSpacing], d.letterSpacing),
    marginX: num("mx", [KEY.marginX, KEY.legacyMargin], d.marginX),
    marginY: num("my", [KEY.marginY, KEY.legacyMargin], d.marginY),
    fullPage: stored(KEY.fullPage) === "1",
    pageTurn: pageTurn(),
    dark: dark(),
    pagerMode: pagerMode(),
    pagerDirection: pagerDirection(),
    pagerTurn:
      stored(KEY.pagerTurn) === "curl" && device.canCurl ? "curl" : "instant",
    pagerPadding: Math.max(0, storedNum(KEY.pagerPadding) ?? d.pagerPadding),
  };
}

// --------------------------------------------------------------- per book

/** Horizontal or vertical, for one book. "auto" (the book's own) is the
 *  absence of a stored value. */
export function storedWritingMode(bookId: string): WritingMode {
  const v = stored(`${KEY.writingMode}:${bookId}`);
  return v === "horizontal" || v === "vertical" ? v : "auto";
}
export function storeWritingMode(bookId: string, value: WritingMode): void {
  const key = `${KEY.writingMode}:${bookId}`;
  if (value === "auto") forget(key);
  else store(key, value);
}

/** Whether one book's pairs are shifted by a page. */
export function storedPagerShift(bookId: string): boolean {
  return stored(`${KEY.pagerShift}:${bookId}`) === "1";
}
export function storePagerShift(bookId: string, value: boolean): void {
  store(`${KEY.pagerShift}:${bookId}`, value ? "1" : "0");
}
