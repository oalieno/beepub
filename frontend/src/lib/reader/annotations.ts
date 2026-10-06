/**
 * AnnotationLayer — saved highlights drawn on the paginator's overlayer.
 *
 * Positions are CFIs (the shape the sync contract stores); the layer
 * resolves them to Ranges in the current section's document and hands the
 * overlayer rects to paint. It stores no geometry of its own: the paginator
 * calls `overlayer.redraw()` after every expand, so a reflow re-measures
 * every drawn range, and a section change rebuilds the drawn set from the
 * CFI list. Colors and shapes arrive resolved (`AnnotationStyle`); what a
 * BeePub color name means stays with the component layer.
 */
import { Overlayer } from "./vendor/foliate/overlayer.js";
import type { NavTarget, OverlayerInstance } from "./core";

/** The three highlight shapes, plus the illustration marker: the gradient
 *  slab the old reader laid over a passage that has an AI illustration
 *  (clickable, pulsing while it generates). */
export type AnnotationKind =
  | "highlight"
  | "underline"
  | "squiggly"
  | "illustration";

export interface AnnotationStyle {
  kind: AnnotationKind;
  /** CSS color — the fill for `highlight`, the stroke for the line kinds;
   *  ignored by `illustration`, whose fill is the fixed gradient. */
  color: string;
  /** `illustration` only: still generating — breathe. */
  pulse?: boolean;
}

export interface Annotation {
  key: string;
  cfi: string;
  style: AnnotationStyle;
}

/**
 * Rects of the text a range covers: one per line fragment per text node.
 * `Range.getClientRects()` would also return the border box of every
 * element the range fully contains — a paragraph-wide slab for a
 * multi-paragraph highlight (and a hit target as big).
 */
export function textRects(range: Range): DOMRect[] {
  const doc = range.startContainer.ownerDocument;
  if (!doc) return [];
  const root = range.commonAncestorContainer;
  const nodes: Text[] = [];
  if (root.nodeType === Node.TEXT_NODE) {
    nodes.push(root as Text);
  } else {
    const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) =>
        range.intersectsNode(node)
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT,
    });
    while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  }
  const rects: DOMRect[] = [];
  for (const node of nodes) {
    const sub = doc.createRange();
    sub.selectNodeContents(node);
    if (node === range.startContainer) sub.setStart(node, range.startOffset);
    if (node === range.endContainer) sub.setEnd(node, range.endOffset);
    if (sub.collapsed) continue;
    for (const r of Array.from(sub.getClientRects())) {
      if (r.width > 0 && r.height > 0) rects.push(r);
    }
  }
  return rects;
}

/** What the overlayer measures: it only ever calls getClientRects().
 *  Keeps the last measurement — the rects as drawn — for hit testing. */
interface RectSource {
  rects: DOMRect[];
  getClientRects(): DOMRect[];
}

function rectSource(range: Range): RectSource {
  return {
    rects: [],
    getClientRects() {
      this.rects = textRects(range);
      return this.rects;
    },
  };
}

const LINE_WIDTH = 2;

const SVG_NS = "http://www.w3.org/2000/svg";

// The illustration marker's fill: purple → blue → pink along the rect's
// diagonal at 30%, multiplied onto the page (the old reader's overlay
// buttons, now as SVG so the paginator re-measures it with the marks).
const ILLUSTRATION_STOPS: [string, string][] = [
  ["0%", "rgb(168,85,247)"],
  ["50%", "rgb(59,130,246)"],
  ["100%", "rgb(236,72,153)"],
];
const ILLUSTRATION_OPACITY = "0.3";
const ILLUSTRATION_RADIUS = 4;
let gradientSerial = 0;

/** One `<linearGradient>` per overlayer SVG (the id must be unique in
 *  the document the SVG lives in; a section change makes a new SVG). */
function ensureIllustrationGradient(svg: SVGElement): string {
  const existing = svg.dataset.illustrationGradient;
  if (existing) return existing;
  const id = `beepub-illustration-fill-${++gradientSerial}`;
  const doc = svg.ownerDocument;
  const defs = doc.createElementNS(SVG_NS, "defs");
  const gradient = doc.createElementNS(SVG_NS, "linearGradient");
  gradient.id = id;
  gradient.setAttribute("x1", "0");
  gradient.setAttribute("y1", "0");
  gradient.setAttribute("x2", "1");
  gradient.setAttribute("y2", "1");
  for (const [offset, color] of ILLUSTRATION_STOPS) {
    const stop = doc.createElementNS(SVG_NS, "stop");
    stop.setAttribute("offset", offset);
    stop.setAttribute("stop-color", color);
    stop.setAttribute("stop-opacity", ILLUSTRATION_OPACITY);
    gradient.append(stop);
  }
  defs.append(gradient);
  svg.prepend(defs);
  svg.dataset.illustrationGradient = id;
  return id;
}

function paintIllustration(
  rects: DOMRect[],
  gradientId: string,
  pulse: boolean,
): SVGElement {
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("fill", `url(#${gradientId})`);
  g.setAttribute("data-kind", "illustration");
  g.style.mixBlendMode = "multiply";
  for (const { left, top, width, height } of rects) {
    const rect = document.createElementNS(SVG_NS, "rect");
    rect.setAttribute("x", String(left));
    rect.setAttribute("y", String(top));
    rect.setAttribute("width", String(width));
    rect.setAttribute("height", String(height));
    rect.setAttribute("rx", String(ILLUSTRATION_RADIUS));
    g.append(rect);
  }
  if (pulse) {
    const animate = document.createElementNS(SVG_NS, "animate");
    animate.setAttribute("attributeName", "opacity");
    animate.setAttribute("values", "1;0.4;1");
    animate.setAttribute("dur", "2s");
    animate.setAttribute("repeatCount", "indefinite");
    g.append(animate);
  }
  return g;
}

function paint(
  rects: DOMRect[],
  style: AnnotationStyle,
  writingMode: string,
): SVGElement {
  switch (style.kind) {
    case "underline":
      return Overlayer.underline(rects, {
        color: style.color,
        width: LINE_WIDTH,
        writingMode,
      });
    case "squiggly":
      return Overlayer.squiggly(rects, {
        color: style.color,
        width: LINE_WIDTH,
        writingMode,
      });
    default:
      return Overlayer.highlight(rects, { color: style.color });
  }
}

/** One rendered section the annotations are drawn on. */
interface Surface {
  overlayer: OverlayerInstance;
  doc: Document;
  index: number;
  writingMode: string;
  /** The annotations drawn here: their Range and the rects the
   *  overlayer last painted for it. */
  drawn: Map<string, { range: Range; source: RectSource }>;
}

function surface(
  overlayer: OverlayerInstance,
  doc: Document,
  index: number,
): Surface {
  // The fill is a pastel at half strength multiplied onto the page, as
  // the old reader's marks pane draws it: on a light page the paper
  // tints, on a dark page the text does.
  const svg = overlayer.element as HTMLElement;
  svg.style.setProperty("--overlayer-highlight-opacity", "0.5");
  svg.style.setProperty("--overlayer-highlight-blend-mode", "multiply");
  return {
    overlayer,
    doc,
    index,
    writingMode: doc.defaultView?.getComputedStyle(doc.body).writingMode ?? "",
    drawn: new Map(),
  };
}

export class AnnotationLayer {
  #items = new Map<string, Annotation>();
  /** The section on screen. */
  #main: Surface | null = null;
  /** Further renderings that show the same annotations and nothing
   *  else — the page-turn slide's ghosts, each under its own key. Never
   *  hit-tested. */
  #mirrors = new Map<object, Surface>();
  #resolve: (cfi: string) => NavTarget | null;

  /** `resolve` turns a CFI into the paginator's navigation target (section
   *  index + a function of the document yielding the Range). */
  constructor(resolve: (cfi: string) => NavTarget | null) {
    this.#resolve = resolve;
  }

  get index() {
    return this.#main?.index ?? -1;
  }

  /** A section rendered: take its overlayer and draw what belongs there. */
  attach(overlayer: OverlayerInstance, doc: Document, index: number) {
    const main = surface(overlayer, doc, index);
    this.#main = main;
    for (const item of this.#items.values()) this.#draw(main, item);
  }

  detach() {
    this.#main = null;
    this.#mirrors.clear();
  }

  /** Another rendering (`key` names it) got a section: draw what
   *  belongs there too. Every later change to the set reaches them all. */
  attachMirror(
    overlayer: OverlayerInstance,
    doc: Document,
    index: number,
    key: object,
  ) {
    const mirror = surface(overlayer, doc, index);
    this.#mirrors.set(key, mirror);
    for (const item of this.#items.values()) this.#draw(mirror, item);
  }

  /** That rendering is gone — or, without a key, all of them are. */
  detachMirror(key?: object) {
    if (key) this.#mirrors.delete(key);
    else this.#mirrors.clear();
  }

  #surfaces(): Surface[] {
    return this.#main
      ? [this.#main, ...this.#mirrors.values()]
      : Array.from(this.#mirrors.values());
  }

  set(item: Annotation) {
    this.#items.set(item.key, item);
    for (const s of this.#surfaces()) {
      this.#undraw(s, item.key);
      this.#draw(s, item);
    }
  }

  delete(key: string) {
    this.#items.delete(key);
    for (const s of this.#surfaces()) this.#undraw(s, key);
  }

  replaceAll(items: Annotation[]) {
    for (const key of Array.from(this.#items.keys()))
      for (const s of this.#surfaces()) this.#undraw(s, key);
    this.#items.clear();
    for (const item of items) this.set(item);
  }

  /** Key of the topmost annotation under a point in the section
   *  document's client coordinates (a click's clientX/Y). Illustration
   *  markers sit above the marks whatever the draw order — the old
   *  reader's overlay buttons did, and a passage that is both
   *  highlighted and illustrated opens its picture on tap. */
  hitTest(x: number, y: number): string | null {
    const drawn = this.#main?.drawn;
    if (!drawn) return null;
    const hit = (kinds: (kind: AnnotationKind) => boolean) => {
      // Most recently drawn first, as the overlayer's own hit test does;
      // against the rects as painted, so no layout work per pointer move.
      const entries = Array.from(drawn.entries()).reverse();
      for (const [key, { source }] of entries) {
        const item = this.#items.get(key);
        if (!item || !kinds(item.style.kind)) continue;
        for (const r of source.rects) {
          if (r.top <= y && r.left <= x && r.bottom > y && r.right > x)
            return key;
        }
      }
      return null;
    };
    return (
      hit((kind) => kind === "illustration") ??
      hit((kind) => kind !== "illustration")
    );
  }

  /** The drawn Range of an annotation in the current section. */
  rangeOf(key: string): Range | null {
    return this.#main?.drawn.get(key)?.range ?? null;
  }

  redraw() {
    this.#main?.overlayer.redraw();
  }

  #draw(s: Surface, item: Annotation) {
    const { overlayer, doc } = s;
    let range: Range | null = null;
    try {
      const target = this.#resolve(item.cfi);
      if (!target || target.index !== s.index) return;
      const anchor =
        typeof target.anchor === "function" ? target.anchor(doc) : null;
      // Cross-realm: the section's Range class is not this window's.
      if (anchor && typeof anchor === "object" && "getClientRects" in anchor) {
        range = anchor as Range;
      }
    } catch {
      range = null;
    }
    if (!range || range.collapsed) return;
    const source = rectSource(range);
    s.drawn.set(item.key, { range, source });
    const { style } = item;
    if (style.kind === "illustration") {
      const gradientId = ensureIllustrationGradient(
        overlayer.element as SVGElement,
      );
      overlayer.add(item.key, source, (rects: DOMRect[]) =>
        paintIllustration(rects, gradientId, !!style.pulse),
      );
      return;
    }
    overlayer.add(item.key, source, (rects: DOMRect[]) =>
      paint(rects, style, s.writingMode),
    );
  }

  #undraw(s: Surface, key: string) {
    s.overlayer.remove(key);
    s.drawn.delete(key);
  }
}
