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
