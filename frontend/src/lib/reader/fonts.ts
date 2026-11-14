/**
 * The typefaces the reader sets a book in.
 *
 * Three are served with the app — a Ming, a Hei and a Kai — so a book
 * looks the same on a phone that ships a good Chinese serif and on one
 * that ships none. Each is cut into about a hundred slices by character
 * range (the stylesheets below), and a page fetches only the slices its
 * own characters fall in. "system" is whatever the device has.
 *
 * A stylesheet is linked into every chapter's document by its URL (see
 * BookReader's fontFaceCss): the slices are then found beside it.
 */
import minchoSheet from "@fontsource-variable/noto-serif-tc/wght.css?url";
import gothicSheet from "@fontsource-variable/noto-sans-tc/wght.css?url";
import kaiSheet from "./fonts/lxgw-wenkai-tc.css?url";
import legacyMingSheet from "./fonts/legacy-ming.css?url";
import legacyMingNames from "./fonts/legacy-ming.json";

/** "system-serif" is the device's own serif: offered by no setting, and
 *  reached only by `?font=serif` — the tests' fixed ground, as
 *  `?turn=instant` is. */
export type ReaderFont =
  | "mincho"
  | "gothic"
  | "kai"
  | "system"
  | "system-serif";

/** The choices the settings offer, in their order. */
export const READER_FONTS = ["mincho", "gothic", "kai", "system"] as const;

export const DEFAULT_READER_FONT: ReaderFont = "mincho";

interface Face {
  /** The family the stylesheet declares (null: nothing is fetched). */
  family: string | null;
  sheet: string | null;
  /** The device's fonts behind it, and which punctuation face leads. */
  serif: boolean;
  /** Device fonts of the same kind, tried before the generic ones. */
  kin: string[];
}

const FACES: Record<ReaderFont, Face> = {
  mincho: {
    family: "Noto Serif TC Variable",
    sheet: minchoSheet,
    serif: true,
    kin: [],
  },
  gothic: {
    family: "Noto Sans TC Variable",
    sheet: gothicSheet,
    serif: false,
    kin: [],
  },
  kai: {
    family: "LXGW WenKai TC",
    sheet: kaiSheet,
    serif: true,
    kin: ["Kaiti TC", "BiauKai", "DFKai-SB", "KaiTi"],
  },
  system: { family: null, sheet: null, serif: false, kin: [] },
  "system-serif": { family: null, sheet: null, serif: true, kin: [] },
};

export function faceOf(font: ReaderFont): Face {
  return FACES[font];
}

/** A stored or asked-for value as a font. The reader once offered
 *  "serif" and "sans-serif", both the device's own: what was chosen then
 *  is now the face of that kind served with the app. */
export function readerFont(value: string | null | undefined): ReaderFont {
  if (value === "serif") return "mincho";
  if (value === "sans-serif") return "gothic";
  return value && value in FACES ? (value as ReaderFont) : DEFAULT_READER_FONT;
}

/*
 * Old Ming and Song fonts — 細明體, PMingLiU, Apple LiSung… — that a
 * book's own CSS asks for by name are drawn badly on a dense screen where
 * the device has them, and are not there at all elsewhere. Such a book is
 * given a stylesheet in which each of those names is the Ming served with
 * the app; a book that names none of them is given nothing.
 */

const LEGACY_MING = new RegExp(
  legacyMingNames.map((n) => n.replace(/ /g, "\\s+")).join("|"),
  "i",
);
const LEGACY_MING_INLINE = legacyMingNames
  .map((n) => `[style*="${n}" i]`)
  .join(",");

function namesLegacyMing(doc: Document): boolean {
  for (const sheet of Array.from(doc.styleSheets)) {
    try {
      for (const rule of Array.from(sheet.cssRules))
        if (LEGACY_MING.test(rule.cssText)) return true;
    } catch {
      // A stylesheet that cannot be read is not one of the book's own.
    }
  }
  return !!doc.querySelector(LEGACY_MING_INLINE);
}

/** For a chapter's document, once it has loaded: its old Ming font
 *  names, if it has any, are set in the app's Ming. */
export function routeLegacyMing(doc: Document) {
  if (!doc.head || !namesLegacyMing(doc)) return;
  const link = doc.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL(legacyMingSheet, window.location.href).href;
  doc.head.append(link);
}

/*
 * Most books name fonts themselves — `p { font-family: serif }` is the
 * common one — and a rule on an element is heard before the page's own
 * list on the body, so the typeface chosen in the settings would reach
 * only the text no rule touches. Each such list in a chapter is
 * therefore led by LEAD_FONTS, a custom property the reader's theme
 * sets to the chosen typeface: the book's own fonts stay behind it, for
 * the characters it lacks (a publisher's font for rare ones) and for
 * the device's own, where the property names no typeface at all.
 */

export const LEAD_FONTS = "--beepub-font";

/** A list that is left as the book has it: code, and what is no list. */
const NOT_LED =
  /mono|courier|consolas|menlo|var\(|^\s*(inherit|initial|unset|revert)/i;

function lead(style: CSSStyleDeclaration) {
  const list = style.getPropertyValue("font-family");
  if (!list || NOT_LED.test(list)) return;
  style.setProperty(
    "font-family",
    `var(${LEAD_FONTS}), ${list}`,
    style.getPropertyPriority("font-family"),
  );
}

function leadRules(rules: CSSRuleList) {
  for (const rule of Array.from(rules)) {
    // (A style rule: an @font-face has a `style` too, and is not one.)
    if ("selectorText" in rule) lead((rule as CSSStyleRule).style);
    if ("cssRules" in rule) leadRules((rule as CSSGroupingRule).cssRules);
  }
}

/** For a chapter's document, once it has loaded: the chosen typeface
 *  leads every font list the book declares. */
export function leadBookFonts(doc: Document) {
  for (const sheet of Array.from(doc.styleSheets)) {
    try {
      leadRules(sheet.cssRules);
    } catch {
      // A stylesheet that cannot be read is not one of the book's own.
    }
  }
  for (const el of Array.from(
    doc.querySelectorAll<HTMLElement>('[style*="font" i]'),
  ))
    lead(el.style);
}
