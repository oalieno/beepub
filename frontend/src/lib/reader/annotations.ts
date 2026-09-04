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

export type AnnotationKind = "highlight" | "underline" | "squiggly";

export interface AnnotationStyle {
  kind: AnnotationKind;
  /** CSS color — the fill for `highlight`, the stroke for the line kinds. */
  color: string;
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

/** What the overlayer measures: it only ever calls getClientRects(). */
function rectSource(range: Range) {
  return { getClientRects: () => textRects(range) };
}

const LINE_WIDTH = 2;

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

export class AnnotationLayer {
  #items = new Map<string, Annotation>();
  /** Ranges of the annotations drawn in the current section. */
  #ranges = new Map<string, Range>();
  #overlayer: OverlayerInstance | null = null;
  #doc: Document | null = null;
  #index = -1;
  #writingMode = "";
  #resolve: (cfi: string) => NavTarget | null;

  /** `resolve` turns a CFI into the paginator's navigation target (section
   *  index + a function of the document yielding the Range). */
  constructor(resolve: (cfi: string) => NavTarget | null) {
    this.#resolve = resolve;
  }

  get index() {
    return this.#index;
  }

  /** A section rendered: take its overlayer and draw what belongs there. */
  attach(overlayer: OverlayerInstance, doc: Document, index: number) {
    this.#overlayer = overlayer;
    this.#doc = doc;
    this.#index = index;
    this.#ranges.clear();
    this.#writingMode =
      doc.defaultView?.getComputedStyle(doc.body).writingMode ?? "";
    // The fill is a pastel at half strength multiplied onto the page, as
    // the old reader's marks pane draws it: on a light page the paper
    // tints, on a dark page the text does.
    const svg = overlayer.element as HTMLElement;
    svg.style.setProperty("--overlayer-highlight-opacity", "0.5");
    svg.style.setProperty("--overlayer-highlight-blend-mode", "multiply");
    for (const item of this.#items.values()) this.#draw(item);
  }

  detach() {
    this.#overlayer = null;
    this.#doc = null;
    this.#index = -1;
    this.#ranges.clear();
  }

  set(item: Annotation) {
    this.#items.set(item.key, item);
    if (!this.#overlayer) return;
    this.#undraw(item.key);
    this.#draw(item);
  }

  delete(key: string) {
    this.#items.delete(key);
    this.#undraw(key);
  }

  replaceAll(items: Annotation[]) {
    for (const key of Array.from(this.#items.keys())) this.#undraw(key);
    this.#items.clear();
    for (const item of items) this.set(item);
  }

  /** Key of the topmost annotation under a point in the section
   *  document's client coordinates (a click's clientX/Y). */
  hitTest(x: number, y: number): string | null {
    const [key] = this.#overlayer?.hitTest({ x, y }) ?? [];
    return typeof key === "string" ? key : null;
  }

  /** The drawn Range of an annotation in the current section. */
  rangeOf(key: string): Range | null {
    return this.#ranges.get(key) ?? null;
  }

  redraw() {
    this.#overlayer?.redraw();
  }

  #draw(item: Annotation) {
    const overlayer = this.#overlayer;
    const doc = this.#doc;
    if (!overlayer || !doc) return;
    let range: Range | null = null;
    try {
      const target = this.#resolve(item.cfi);
      if (!target || target.index !== this.#index) return;
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
    this.#ranges.set(item.key, range);
    overlayer.add(item.key, rectSource(range), (rects: DOMRect[]) =>
      paint(rects, item.style, this.#writingMode),
    );
  }

  #undraw(key: string) {
    this.#overlayer?.remove(key);
    this.#ranges.delete(key);
  }
}
