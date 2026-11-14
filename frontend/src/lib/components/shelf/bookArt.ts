// What a book looks like: the colour its binding takes from its cover,
// the face of its spine (drawn once per book), and a cover for a book
// that has none.
import * as THREE from "three";
import type { Part, ShelfBook } from "./engine";

export type RGB = [number, number, number];
export interface Look {
  cloth: RGB;
  ratio: number;
}

const SERIF =
  '"Noto Serif TC Variable", "Noto Serif CJK TC", "Source Han Serif TC", "Songti TC", "PMingLiU", serif';
export const PAPER: RGB = [232, 218, 190];
// For a book with no cover: quiet cloth colours.
const CLOTHS: RGB[] = [
  [96, 58, 46],
  [50, 68, 84],
  [66, 82, 60],
  [122, 96, 56],
  [86, 60, 90],
  [48, 54, 62],
  [128, 72, 52],
];

// ---- colour ------------------------------------------------------------
export const hex = (c: RGB) =>
  "#" + c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
export const lum = (c: RGB) => {
  const f = (v: number) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
};
export const inkOn = (c: RGB) => (lum(c) > 0.34 ? "#33291f" : "#f3ead8");
export const srgb = (c: RGB) =>
  new THREE.Color().setRGB(
    c[0] / 255,
    c[1] / 255,
    c[2] / 255,
    THREE.SRGBColorSpace,
  );
// A light's colour, given as it is used (no conversion).
export const raw = (n: number) =>
  new THREE.Color().setHex(n, THREE.LinearSRGBColorSpace);
export const std = (c: RGB, rough = 0.9) =>
  new THREE.MeshStandardMaterial({
    color: srgb(c),
    roughness: rough,
    metalness: 0,
  });

export function hash(s: string) {
  let n = 2166136261;
  for (let i = 0; i < s.length; i++) {
    n ^= s.charCodeAt(i);
    n = Math.imul(n, 16777619);
  }
  return n >>> 0;
}

// The binding takes the cover's own colour: what the cover is along the
// edge where the spine joins it, as it is.
const looks = new Map<string, Promise<Look>>();
export function lookOf(b: ShelfBook): Promise<Look> {
  const plain: Look = {
    cloth: CLOTHS[hash(b.id) % CLOTHS.length],
    ratio: 1.45,
  };
  if (!b.cover) return Promise.resolve(plain);
  const known = looks.get(b.cover);
  if (known) return known;
  const made = new Promise<Look>((done) => {
    const img = new Image();
    const give = (l: Look) => {
      clearTimeout(timer);
      done(l);
    };
    const timer = setTimeout(() => give(plain), 6000);
    img.onerror = () => give(plain);
    img.onload = () => {
      try {
        const cv = document.createElement("canvas");
        cv.width = 6;
        cv.height = 60;
        const g = cv.getContext("2d", { willReadFrequently: true })!;
        const strip = Math.max(3, Math.round(img.naturalWidth * 0.07));
        g.drawImage(img, 0, 0, strip, img.naturalHeight, 0, 0, 6, 60);
        const px = g.getImageData(0, 0, 6, 60).data;
        // The fullest of 512 bins, then everything close to it, averaged.
        const bins = new Map<number, number>();
        for (let i = 0; i < px.length; i += 4) {
          const k =
            ((px[i] >> 5) << 6) | ((px[i + 1] >> 5) << 3) | (px[i + 2] >> 5);
          bins.set(k, (bins.get(k) ?? 0) + 1);
        }
        let top = 0;
        let most = -1;
        for (const [k, n] of bins) if (n > most) [top, most] = [k, n];
        const mid = [
          (top >> 6) * 32 + 16,
          ((top >> 3) & 7) * 32 + 16,
          (top & 7) * 32 + 16,
        ];
        let r = 0;
        let gr = 0;
        let bl = 0;
        let n = 0;
        for (let i = 0; i < px.length; i += 4) {
          const far = Math.hypot(
            px[i] - mid[0],
            px[i + 1] - mid[1],
            px[i + 2] - mid[2],
          );
          if (far > 44) continue;
          r += px[i];
          gr += px[i + 1];
          bl += px[i + 2];
          n++;
        }
        give({
          cloth: n ? [r / n, gr / n, bl / n] : plain.cloth,
          ratio: Math.min(
            1.56,
            Math.max(1.34, img.naturalHeight / img.naturalWidth),
          ),
        });
      } catch {
        give(plain);
      }
    };
    img.src = b.cover!;
  });
  looks.set(b.cover, made);
  return made;
}

// ---- the spine's face, drawn once per book ----------------------------
const PUNCT = "，、。";
const TURNED = "（）「」『』《》〈〉【】〔〕()[]—–-…～~";
// A Latin word keeps its own hyphens, apostrophes and commas: "Wild-Built"
// is one run, not three.
const LATIN = "[A-Za-z0-9\\u00C0-\\u024F][A-Za-z0-9\\u00C0-\\u024F.'’&,!?-]*";
const LATIN_ONLY = new RegExp(`^${LATIN}$`);
const TOKENS = new RegExp(`${LATIN}|\\s+|.`, "gu");
const isLatin = (t: string) => LATIN_ONLY.test(t);
const tokensOf = (s: string) => s.match(TOKENS) ?? [];
export const lengthOf = (tokens: string[]) =>
  tokens.reduce(
    (n, t) =>
      n +
      (/^\s+$/.test(t)
        ? 0.4
        : isLatin(t)
          ? t.length * 0.6 + 0.12
          : PUNCT.includes(t)
            ? 0.62
            : 1),
    0,
  );
// One column of text, top to bottom: CJK upright, Latin and digits on
// their side as on a real spine. Stops at `limit`.
function column(
  g: CanvasRenderingContext2D,
  tokens: string[],
  cx: number,
  top: number,
  size: number,
  step: number,
  limit: number,
) {
  let y = top + step / 2;
  for (const t of tokens) {
    if (/^\s+$/.test(t)) {
      y += step * 0.3;
      continue;
    }
    if (isLatin(t)) {
      // As long as it measures: an estimate leaves a hole after a word
      // of narrow letters.
      const w = g.measureText(t).width + size * 0.08;
      if (y - step / 2 + w > limit) break;
      // Set from where the run begins, not about its middle: a narrow
      // "11" starts where a wide "12" does on the next spine.
      g.save();
      g.translate(cx, y - step / 2);
      g.rotate(Math.PI / 2);
      g.textAlign = "left";
      g.fillText(t, size * 0.04, 0);
      g.restore();
      y += w;
      continue;
    }
    if (y + step / 2 > limit) break;
    if (PUNCT.includes(t)) {
      // Vertical punctuation sits in the upper right of its cell.
      g.fillText(t, cx + size * 0.52, y - size * 0.5);
      y += step * 0.62;
    } else if (TURNED.includes(t)) {
      g.save();
      g.translate(cx, y);
      g.rotate(Math.PI / 2);
      g.fillText(t, 0, 0);
      g.restore();
      y += step;
    } else {
      g.fillText(t, cx, y);
      y += step;
    }
  }
}

// The title as a spine carries it: without what is added in brackets
// (an edition, a box set's contents, a blurb) — unless nothing is left.
function spineTitle(title: string) {
  const bare = title
    .replace(/[（(【〔\[][^）)】〕\]]*(?:[）)】〕\]]|$)/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[\s：:—-]+$/, "")
    .trim();
  return bare || title.trim();
}

// A title and its subtitle: parted at the first colon (or long dash)
// that has words on both sides. No subtitle: the second part is empty.
export function titleParts(tokens: string[]): [string[], string[]] {
  const at = tokens.findIndex(
    (t, n) => n > 0 && n < tokens.length - 1 && "：:—".includes(t),
  );
  if (at < 0) return [tokens, []];
  const main = tokens.slice(0, at);
  const sub = tokens.slice(at + 1);
  while (sub.length && (/^\s+$/.test(sub[0]) || sub[0] === "—")) sub.shift();
  while (main.length && /^\s+$/.test(main[main.length - 1])) main.pop();
  if (!main.length || !sub.length) return [tokens, []];
  // A title in Latin letters lies on its side and takes the spine's whole
  // length: there is no room under it, so its subtitle is left off.
  if (main.every((t) => isLatin(t) || /^\s+$/.test(t))) return [main, []];
  return [main, sub];
}

// Where the title goes on a spine of this height and width, under this
// author's name.
export function spinePlan(h: number, w: number, who: string, title: string) {
  const authorPx = Math.max(10, Math.min(14, Math.round(w * 0.27)));
  const authorStep = authorPx * 1.16;
  const authorLen = Math.min(lengthOf(tokensOf(who)) * authorStep, h * 0.34);
  const authorTop = h - 40 - authorLen;
  const top = Math.round(h * 0.055);
  const start = top + Math.round(h * 0.045);
  const room = authorTop - 22 - start;
  const tokens = tokensOf(spineTitle(title));
  const fit = (t: string[]) => Math.floor(room / (lengthOf(t) * 1.12));
  return {
    authorPx,
    authorStep,
    authorTop,
    top,
    start,
    room,
    tokens,
    fit,
  };
}
export function spineCanvas(p: Part) {
  const k = 2; // drawn at 2x: sharp on a dense screen, and near enough in hand
  const cv = document.createElement("canvas");
  cv.width = p.w * k;
  cv.height = p.h * k;
  const g = cv.getContext("2d")!;
  g.scale(k, k);
  const c = p.look!.cloth;
  g.fillStyle = hex(c);
  g.fillRect(0, 0, p.w, p.h);
  g.fillStyle = inkOn(c);
  g.textAlign = "center";
  g.textBaseline = "middle";
  const cx = p.w / 2;
  const rule = (y: number, w: number, a: number) => {
    g.globalAlpha = a;
    g.fillRect(cx - w / 2, y, w, 1);
    g.globalAlpha = 1;
  };

  // Sizes follow the spine's width: the title about half of it, the
  // author about a quarter.
  // The volumes of a series are lettered alike, whatever their thickness:
  // a size that differs by a pixel puts every character out of line with
  // the next spine's.
  const titlePx = p.b.series
    ? 19
    : Math.max(17, Math.min(30, Math.round(p.w * 0.52)));
  const { authorPx, authorStep, authorTop, top, start, room, tokens, fit } =
    spinePlan(p.h, p.w, p.who, p.b.title);
  rule(top, p.w * 0.56, 0.35);

  // The foot, from the bottom up: a rule, the author.
  rule(p.h - 24, 14, 0.4);
  const who = tokensOf(p.who);
  g.font = `500 ${authorPx}px ${SERIF}`;
  g.globalAlpha = 0.8;
  column(g, who, cx, authorTop, authorPx, authorStep, p.h - 36);
  g.globalAlpha = 1;

  const limit = start + room;
  const fadeOut = (overflows: boolean, step: number) => {
    if (!overflows) return;
    const fade = g.createLinearGradient(0, limit - step * 2.6, 0, limit + 2);
    fade.addColorStop(0, `rgba(${c.map(Math.round).join(",")},0)`);
    fade.addColorStop(1, hex(c));
    g.fillStyle = fade;
    g.fillRect(0, limit - step * 2.6, p.w, step * 2.6 + 4);
    g.fillStyle = inkOn(c);
  };
  const [main, sub] = titleParts(tokens);
  if (!sub.length) {
    // The title: one column from a tenth of the way down, set smaller
    // when it is long. One too long even at the smallest size fades out
    // at its foot.
    const size = Math.max(11, Math.min(titlePx, fit(main)));
    const step = size * 1.12;
    g.font = `700 ${size}px ${SERIF}`;
    column(g, main, cx, start, size, step, limit + 1);
    fadeOut(lengthOf(main) * step > room + 1, step);
    return cv;
  }
  // A title with a subtitle is set as a real spine sets it: the title
  // large, a gap where the colon was, the subtitle small under it
  // — in one column if that fits, else in two, right then left.
  const lm = lengthOf(main);
  const ls = lengthOf(sub);
  // Between them only a gap: the change of size says the rest.
  const pad = (start - top) * 0.45;
  let sm = titlePx;
  let ss = 0;
  let cols: string[][] = [sub];
  for (; sm >= 13; sm--) {
    ss = Math.max(10, Math.round(sm * 0.58));
    if (lm * 1.12 * sm + pad + ls * 1.12 * ss <= room) break;
  }
  if (sm < 13) {
    // Two columns: broken at a pause near the middle, else at the middle.
    let cut = 1;
    let best = Infinity;
    for (let n = 1; n < sub.length; n++) {
      const off = Math.abs(lengthOf(sub.slice(0, n)) - ls / 2);
      const pause = /^\s+$/.test(sub[n]) || "，、：:—".includes(sub[n - 1]);
      const score = off - (pause && off < ls * 0.25 ? ls : 0);
      if (score < best) [cut, best] = [n, score];
    }
    const second = sub.slice(cut);
    while (second.length && /^\s+$/.test(second[0])) second.shift();
    cols = [sub.slice(0, cut), second];
    const longest = Math.max(lengthOf(cols[0]), lengthOf(cols[1]));
    for (sm = titlePx; sm > 13; sm--) {
      ss = Math.max(
        9,
        Math.min(Math.round(sm * 0.5), Math.floor((p.w - 10) / 2)),
      );
      if (lm * 1.12 * sm + pad + longest * 1.12 * ss <= room) break;
    }
    ss = Math.max(
      9,
      Math.min(Math.round(sm * 0.5), Math.floor((p.w - 10) / 2)),
    );
  }
  g.font = `700 ${sm}px ${SERIF}`;
  column(g, main, cx, start, sm, sm * 1.12, limit + 1);
  const mainEnd = start + lm * 1.12 * sm;
  const subTop = mainEnd + pad;
  g.font = `600 ${ss}px ${SERIF}`;
  g.globalAlpha = 0.92;
  if (cols.length === 1) column(g, sub, cx, subTop, ss, ss * 1.12, limit + 1);
  else {
    column(g, cols[0], cx + ss * 0.6, subTop, ss, ss * 1.12, limit + 1);
    column(g, cols[1], cx - ss * 0.6, subTop, ss, ss * 1.12, limit + 1);
  }
  g.globalAlpha = 1;
  const longest = Math.max(...cols.map(lengthOf));
  fadeOut(subTop + longest * 1.12 * ss > limit + 1, ss * 1.12);
  return cv;
}

// A cover for a book that has none: its cloth, its title.
export function plainCover(p: Part) {
  const cv = document.createElement("canvas");
  cv.width = 400;
  cv.height = Math.round(400 * p.look!.ratio);
  const g = cv.getContext("2d")!;
  const c = p.look!.cloth;
  g.fillStyle = hex(c);
  g.fillRect(0, 0, cv.width, cv.height);
  g.fillStyle = inkOn(c);
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.globalAlpha = 0.4;
  g.fillRect(cv.width / 2 - 30, cv.height * 0.2, 60, 2);
  g.globalAlpha = 1;
  g.font = `700 40px ${SERIF}`;
  const chars = [...p.b.title];
  const per = 8;
  const lines: string[] = [];
  for (let i = 0; i < chars.length && lines.length < 4; i += per)
    lines.push(chars.slice(i, i + per).join(""));
  lines.forEach((l, n) =>
    g.fillText(l, cv.width / 2, cv.height * 0.32 + n * 56),
  );
  g.font = `500 22px ${SERIF}`;
  g.globalAlpha = 0.8;
  g.fillText(p.b.author.slice(0, 16), cv.width / 2, cv.height * 0.82);
  return cv;
}
