/**
 * PageCurl — the "curl" page turn: a sheet lifted by its corner and folded
 * over the spine, the way a printed page is turned.
 *
 * The fold is flat, not bent: the sheet's grabbed point C is carried to P,
 * the fold is the perpendicular bisector of C and P, and what lies on C's
 * side of it is reflected across it. That needs nothing but a clip path and
 * a reflection matrix on ordinary DOM, so whatever the sheet holds — an
 * image, a laid-out page — turns without being rasterised.
 *
 * Everything is worked out in the sheet's own frame: the spine is the line
 * x = 0 and the sheet spans x in [0, W]. A sheet whose spine is on its
 * right (a manga, vertical text) is drawn in a stage mirrored about its
 * centre; the pages put into it are mirrored back by the caller.
 *
 * Progress p runs from 0 (lying flat, on the spine's far side) to 1 (turned
 * over). A finger can lift a sheet only so far (`held`); letting go, or a
 * tap, finishes the turn along a low arc (`pointAt`) that leaves and
 * reaches the flat sheet on a slant — a fold square to an edge would turn
 * the whole strip along that edge over for a frame. The shading (the
 * shadow on the flap, the shadow it casts, the gutter of a spread) is as
 * strong as the sheet is lifted and fades out before it lies flat again,
 * so no shadow ever just vanishes.
 *
 * Behaviour follows the approved prototype, `.docs/designs/page-curl-demo.html`.
 */

export interface Point {
  x: number;
  y: number;
}

/** A turn's direction: 1 turns the sheet over (forward), -1 brings the
 *  previous sheet back over the spine. */
export type CurlDirection = 1 | -1;

// ------------------------------------------------------------- geometry

/** Sutherland–Hodgman: the part of a convex polygon where g ≥ 0. */
export function clipPolygon(pts: Point[], g: (p: Point) => number): Point[] {
  const out: Point[] = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    const ga = g(a);
    const gb = g(b);
    if (ga >= 0) out.push(a);
    if (ga >= 0 !== gb >= 0) {
      const t = ga / (ga - gb);
      out.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
    }
  }
  return out;
}

export function polygonCss(pts: Point[]): string {
  return pts.length
    ? `polygon(${pts.map((q) => `${q.x.toFixed(2)}px ${q.y.toFixed(2)}px`).join(",")})`
    : "polygon(0 0,0 0,0 0)";
}

/** A sheet stays fixed to its spine: its corner can be no further from
 *  the spine's end on the same edge than the sheet is wide, nor further
 *  from the other end than the sheet's diagonal. */
export function clampToSpine(
  P: Point,
  W: number,
  H: number,
  cy: number,
): Point {
  const S = { x: 0, y: cy };
  const S2 = { x: 0, y: H - cy };
  const D = Math.hypot(W, H);
  let q = P;
  for (let k = 0; k < 3; k++) {
    let dx = q.x - S.x;
    let dy = q.y - S.y;
    let d = Math.hypot(dx, dy);
    if (d > W) q = { x: S.x + (dx / d) * W, y: S.y + (dy / d) * W };
    dx = q.x - S2.x;
    dy = q.y - S2.y;
    d = Math.hypot(dx, dy);
    if (d > D) q = { x: S2.x + (dx / d) * D, y: S2.y + (dy / d) * D };
  }
  return q;
}

/** The corner's way across: p along the turn, raised on a low arc, plus
 *  the finger's own height above that arc (yDev). */
export function pointAt(
  p: number,
  yDev: number,
  W: number,
  H: number,
  cy: number,
): Point {
  const y = cy + yDev + (cy > H / 2 ? -arcLift(p, H) : arcLift(p, H));
  return clampToSpine({ x: W - 2 * W * p, y }, W, H, cy);
}

function arcLift(p: number, H: number): number {
  return Math.sin(Math.max(0, Math.min(1, p)) * Math.PI) * H * 0.14;
}

/** How strongly a turn shades: nothing on a sheet lying flat, full while
 *  it is lifted, fading out again as it settles on the other side. */
export function strength(p: number): number {
  return (
    Math.min(1, Math.max(0, p / 0.08)) *
    Math.min(1, Math.max(0, (1 - p) / 0.35))
  );
}

/** A sheet up to this wide is phone-sized: its turn takes the time and
 *  casts the shade it was made with. A wider one (a tablet, a desktop
 *  window) turns more slowly, and its shade grows no wider. */
const PHONE_WIDTH = 500;

/** As in Apple Books, a finger lifts a sheet only so far; past that it
 *  gives a little and stops, and letting go finishes the turn. A sheet
 *  being brought back cannot be laid down by the finger either. */
export const HOLD_MAX = { single: 0.6, spread: 0.68 } as const;
export const HOLD_MIN = 0.4;
const HOLD_GIVE = 0.05;

export function held(raw: number, spread: boolean, dir: CurlDirection): number {
  if (dir > 0) {
    const hi = spread ? HOLD_MAX.spread : HOLD_MAX.single;
    const r = Math.max(0, raw);
    return r > hi ? hi + HOLD_GIVE * (1 - Math.exp(-(r - hi) * 6)) : r;
  }
  const r = Math.min(1, raw);
  return r < HOLD_MIN
    ? HOLD_MIN - HOLD_GIVE * (1 - Math.exp(-(HOLD_MIN - r) * 6))
    : r;
}

/** Turning back a single sheet, the previous sheet does not wait for the
 *  finger: it comes over the spine at once, as far as LEAD, and the finger
 *  takes it from there. A spread has no lead: its sheet follows the finger
 *  from the start. */
export const LEAD = 0.8;
export const LEAD_MS = 260;

export interface Fold {
  /** The part of the sheet still lying on the spine's side. */
  front: Point[];
  /** The part folded over, in the sheet's own (unreflected) frame. */
  folded: Point[];
  /** `folded` where it now lies, reflected across the fold. */
  lying: Point[];
  /** CSS matrix() reflecting the sheet across the fold. */
  matrix: string;
  /** The fold's midpoint and its angle (degrees) towards C. */
  mid: Point;
  angle: number;
  /** |C − P|. */
  reach: number;
  /** The fold's x nearest the spine, within the sheet. */
  nearest: number;
}

/** The fold for corner C = (W, cy) carried to P; null while the sheet lies
 *  flat. */
export function foldAt(
  P: Point,
  W: number,
  H: number,
  cy: number,
): Fold | null {
  const dx = W - P.x;
  const dy = cy - P.y;
  const d = Math.hypot(dx, dy);
  if (d < 0.5) return null;
  const nx = dx / d;
  const ny = dy / d;
  const mx = (W + P.x) / 2;
  const my = (cy + P.y) / 2;
  const k = mx * nx + my * ny;
  const side = (q: Point) => q.x * nx + q.y * ny - k; // > 0 on C's side
  const rect = [
    { x: 0, y: 0 },
    { x: W, y: 0 },
    { x: W, y: H },
    { x: 0, y: H },
  ];
  const folded = clipPolygon(rect, side);
  const lying = folded.map((q) => {
    const t = 2 * side(q);
    return { x: q.x - t * nx, y: q.y - t * ny };
  });
  const at = (y: number) => (Math.abs(nx) < 1e-6 ? W : (k - ny * y) / nx);
  return {
    front: clipPolygon(rect, (q) => -side(q)),
    folded,
    lying,
    matrix: `matrix(${1 - 2 * nx * nx},${-2 * nx * ny},${-2 * nx * ny},${1 - 2 * ny * ny},${2 * k * nx},${2 * k * ny})`,
    mid: { x: mx, y: my },
    angle: (Math.atan2(ny, nx) * 180) / Math.PI,
    reach: d,
    nearest: Math.max(0, Math.min(W, at(0), at(H))),
  };
}

// ------------------------------------------------------------- renderer

const SVG_NS = "http://www.w3.org/2000/svg";

function el(tag: string, style: Partial<CSSStyleDeclaration>): HTMLElement {
  const e = document.createElement(tag);
  Object.assign(e.style, style);
  return e;
}

/** A sheet for the fold layer: where it lies, which way its spine is,
 *  and what its back shows. */
export interface FoldSheet {
  /** The sheet in the layer's parent's coordinates, px. */
  left: number;
  top: number;
  width: number;
  height: number;
  /** The spine is on the sheet's right (the stage is mirrored). */
  mirror: boolean;
  /** What its back shows; null: bare paper. */
  back: HTMLElement | null;
  /** The back is the same page seen through the paper (a single page):
   *  it is veiled, and comes out mirrored. */
  seeThrough: boolean;
  /** Paper colour, behind the sheet's faces and in the veil. */
  paper: string;
}

/**
 * The drawing of a fold, without any say in when or how far: the sheet's
 * front cut along the fold, the flap folded over it with its shading, the
 * flap's shadow, and the shade it casts on what it uncovers.
 *
 * The front is either a node put into the layer (`setFront`), or an
 * element that stays where it is beneath the layer (`setFrontInPlace`) —
 * one that cannot be moved, such as a laid-out page in an iframe, which
 * would load again if it were. That one is cut by a clip path on itself,
 * in its own frame: it is expected to cover the sheet's rectangle exactly.
 */
export class FoldLayer {
  /** Goes into the parent the sheet is measured in, over the pages. */
  readonly root: HTMLElement;
  #stage: HTMLElement;
  #cast: HTMLElement;
  #castShade: HTMLElement;
  #front: HTMLElement;
  #frontSlot: HTMLElement;
  #inPlace: HTMLElement | null = null;
  #shadow: SVGSVGElement;
  #shadowPoly: SVGPolygonElement;
  #back: HTMLElement;
  #backSlot: HTMLElement;
  #veil: HTMLElement;
  #backShade: HTMLElement;
  /** A back that stays in the layer between turns (see holdBack). */
  #heldBack: HTMLElement | null = null;
  #sheet: FoldSheet | null = null;

  constructor() {
    this.root = el("div", { position: "absolute", pointerEvents: "none" });
    this.#stage = el("div", {
      position: "absolute",
      left: "0",
      top: "0",
      transformOrigin: "50% 50%",
    });
    const fill = {
      position: "absolute",
      left: "0",
      top: "0",
      width: "100%",
      height: "100%",
    };
    this.#cast = el("div", { ...fill, overflow: "visible" });
    this.#castShade = el("div", {
      position: "absolute",
      left: "0",
      top: "0",
      transformOrigin: "0 0",
    });
    this.#cast.append(this.#castShade);
    this.#front = el("div", { ...fill, overflow: "hidden" });
    this.#frontSlot = el("div", fill);
    this.#front.append(this.#frontSlot);
    this.#shadow = document.createElementNS(SVG_NS, "svg");
    this.#shadow.setAttribute("aria-hidden", "true");
    Object.assign(this.#shadow.style, {
      position: "absolute",
      top: "0",
      overflow: "visible",
    });
    const defs = document.createElementNS(SVG_NS, "defs");
    const filter = document.createElementNS(SVG_NS, "filter");
    const filterId = `curl-blur-${Math.random().toString(36).slice(2, 8)}`;
    filter.setAttribute("id", filterId);
    for (const [k, v] of [
      ["x", "-30%"],
      ["y", "-30%"],
      ["width", "160%"],
      ["height", "160%"],
    ])
      filter.setAttribute(k, v);
    const blur = document.createElementNS(SVG_NS, "feGaussianBlur");
    blur.setAttribute("stdDeviation", "22");
    filter.append(blur);
    defs.append(filter);
    this.#shadowPoly = document.createElementNS(SVG_NS, "polygon");
    this.#shadowPoly.setAttribute("fill", "#000");
    this.#shadowPoly.setAttribute("filter", `url(#${filterId})`);
    this.#shadow.append(defs, this.#shadowPoly);
    // The flap's shadow is a blurred SVG outline rather than a CSS
    // drop-shadow: WebKit leaves stale paint behind a filtered element
    // whose clip path moves every frame.
    const backWrap = el("div", fill);
    this.#back = el("div", {
      ...fill,
      overflow: "hidden",
      transformOrigin: "0 0",
    });
    this.#backSlot = el("div", fill);
    this.#veil = el("div", {
      position: "absolute",
      inset: "0",
      opacity: ".86",
    });
    this.#backShade = el("div", {
      position: "absolute",
      left: "0",
      top: "0",
      transformOrigin: "0 0",
      pointerEvents: "none",
    });
    this.#back.append(this.#backSlot, this.#veil, this.#backShade);
    backWrap.append(this.#back);
    this.#stage.append(this.#cast, this.#front, this.#shadow, backWrap);
    this.root.append(this.#stage);
  }

  /**
   * Sets up a sheet. `clipToSheet`: nothing of the fold shows outside the
   * sheet (a single page: what goes past the spine is gone); otherwise
   * the layer covers its parent, which clips (a spread: the flap lands on
   * the facing page).
   */
  setSheet(sheet: FoldSheet, clipToSheet: boolean) {
    this.#sheet = sheet;
    const { left, top, width: W, height: H } = sheet;
    Object.assign(
      this.root.style,
      clipToSheet
        ? {
            left: `${left}px`,
            top: `${top}px`,
            width: `${W}px`,
            height: `${H}px`,
            overflow: "hidden",
          }
        : {
            left: "0",
            top: "0",
            width: "100%",
            height: "100%",
            overflow: "hidden",
          },
    );
    Object.assign(this.#stage.style, {
      left: `${clipToSheet ? 0 : left}px`,
      top: `${clipToSheet ? 0 : top}px`,
      width: `${W}px`,
      height: `${H}px`,
      transform: sheet.mirror ? "scaleX(-1)" : "none",
    });
    this.#front.style.background = sheet.paper;
    this.#back.style.background = sheet.paper;
    this.#veil.style.background = sheet.paper;
    this.#veil.hidden = !sheet.seeThrough;
    if (this.#heldBack) {
      // (Put in once: one that is moved, an iframe, would load again.)
    } else if (sheet.back) this.#backSlot.replaceChildren(sheet.back);
    else this.#backSlot.replaceChildren();
    const diag = Math.ceil(Math.hypot(W, H)) * 2;
    for (const sh of [this.#backShade, this.#castShade]) {
      sh.style.width = `${diag}px`;
      sh.style.height = `${diag * 2}px`;
    }
    Object.assign(this.#shadow.style, {
      left: `${-W}px`,
      width: `${2 * W}px`,
      height: `${H}px`,
    });
    this.#shadow.setAttribute("viewBox", `${-W} 0 ${2 * W} ${H}`);
  }

  /** `element` is the back of every sheet from now on (null: no
   *  longer), and stays in the layer between turns — a laid-out page in
   *  an iframe, which would load again if it were moved. It is put into
   *  the back as it is, so it should cover the sheet's rectangle. */
  holdBack(element: HTMLElement | null) {
    if (this.#heldBack === element) return;
    this.#heldBack = element;
    this.#backSlot.replaceChildren(...(element ? [element] : []));
  }

  /** The sheet's front is `node`, put into the layer (already mirrored
   *  back by the caller if the sheet is). */
  setFront(node: HTMLElement) {
    this.#releaseInPlace();
    this.#front.hidden = false;
    this.#frontSlot.replaceChildren(node);
  }

  /** The sheet's front is `element`, left where it is beneath the layer
   *  and cut by a clip path of its own. */
  setFrontInPlace(element: HTMLElement) {
    if (this.#inPlace !== element) this.#releaseInPlace();
    this.#inPlace = element;
    this.#frontSlot.replaceChildren();
    this.#front.hidden = true;
  }

  #releaseInPlace() {
    if (this.#inPlace) this.#inPlace.style.clipPath = "";
    this.#inPlace = null;
  }

  /** Draws corner C = (W, cy) carried to P, p of the way over; returns
   *  the fold (null: the sheet lies flat). */
  draw(P: Point, p: number, cy: number): Fold | null {
    const s = this.#sheet;
    if (!s) return null;
    const fold = foldAt(P, s.width, s.height, cy);
    if (!fold) {
      this.#front.style.clipPath = "none";
      if (this.#inPlace) this.#inPlace.style.clipPath = "";
      this.#back.style.clipPath = polygonCss([]);
      this.#castShade.style.opacity = "0";
      this.#shadowPoly.setAttribute("points", "");
      return null;
    }
    const a = strength(p);
    this.#front.style.clipPath = polygonCss(fold.front);
    if (this.#inPlace) {
      // In the element's own frame: unmirrored, and offset by nothing —
      // it covers the sheet.
      const W = s.width;
      this.#inPlace.style.clipPath = polygonCss(
        s.mirror ? fold.front.map((q) => ({ x: W - q.x, y: q.y })) : fold.front,
      );
    }
    this.#back.style.clipPath = polygonCss(fold.folded);
    this.#back.style.transform = fold.matrix;
    this.#shadowPoly.setAttribute(
      "points",
      fold.lying.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" "),
    );
    this.#shadowPoly.setAttribute("fill-opacity", (0.24 * a).toFixed(3));
    const depth = Math.max(
      8,
      Math.min(fold.reach / 2, Math.min(s.width, PHONE_WIDTH) * 0.6),
    );
    const at = `translate(${fold.mid.x}px,${fold.mid.y}px) rotate(${fold.angle}deg) translateY(-50%)`;
    // On the flap: paper, a little darker where it bends at the fold
    // — no sheen, no bands.
    this.#backShade.style.transform = at;
    this.#backShade.style.opacity = String(a);
    this.#backShade.style.background = `linear-gradient(90deg, rgba(0,0,0,.12) 0, rgba(0,0,0,.05) ${depth * 0.25}px, rgba(0,0,0,0) ${depth * 0.7}px)`;
    // On the page the lifted sheet uncovers.
    const reach = Math.max(24, depth * 0.9);
    this.#castShade.style.opacity = String(a);
    this.#castShade.style.transform = at;
    // (Eased off in many steps: a shade with an edge to it is a line.)
    this.#castShade.style.background = `linear-gradient(90deg, rgba(0,0,0,.20) 0, rgba(0,0,0,.13) ${reach * 0.15}px, rgba(0,0,0,.07) ${reach * 0.35}px, rgba(0,0,0,.03) ${reach * 0.6}px, rgba(0,0,0,0) ${reach}px)`;
    this.#cast.style.clipPath = polygonCss(fold.folded);
    return fold;
  }

  /** Nothing drawn; the sheet's faces out of the layer, and an in-place
   *  front whole again. */
  clear() {
    this.#releaseInPlace();
    this.#frontSlot.replaceChildren();
    if (!this.#heldBack) this.#backSlot.replaceChildren();
    this.#sheet = null;
  }
}

/** A sheet for PageCurl: a FoldSheet whose front is put into the layer. */
export interface CurlSheet extends Omit<FoldSheet, "back"> {
  /** One page of a two-page spread: the flap may lie over the other
   *  page, the gutter shades, and a sheet brought back has no lead. */
  spread: boolean;
  /** What the sheet shows, already mirrored back if `mirror`. */
  front: HTMLElement;
  /** What its back shows. */
  back: HTMLElement;
}

/**
 * Draws a turn into a host element (positioned, covering the area the
 * pages are laid out in). The caller puts what lies under the sheet into
 * `base`, sets up a sheet, then drives it by a finger (`grab`, `follow`,
 * `release`) or plays it whole (`play`). A turn that has ended stays drawn
 * at its last frame until `clear`, so the caller can land the reader's own
 * page underneath first.
 */
export class PageCurl {
  readonly base: HTMLElement;
  #host: HTMLElement;
  #gutter: HTMLElement;
  #layer: FoldLayer;

  #sheet: CurlSheet | null = null;
  #turn: {
    dir: CurlDirection;
    cy: number;
    /** p the turn started from: 0 forward, 1 back. */
    from: number;
    P: Point | null;
    p: number;
  } | null = null;
  #drag: {
    x0: number;
    y0: number;
    last: { x: number; y: number; t: number };
    prev: { x: number; y: number; t: number };
    lead: number | null;
    yDev: number;
  } | null = null;
  #frame: number | null = null;
  #settle: (() => void) | null = null;

  constructor(host: HTMLElement) {
    this.#host = host;
    this.base = el("div", { position: "absolute", inset: "0" });
    this.#gutter = el("div", {
      position: "absolute",
      top: "0",
      bottom: "0",
      width: "72px",
      transform: "translateX(-50%)",
      pointerEvents: "none",
      opacity: "0",
      background:
        "linear-gradient(90deg, rgba(0,0,0,0) 0, rgba(0,0,0,.10) 40%, rgba(0,0,0,.24) 50%, rgba(0,0,0,.10) 60%, rgba(0,0,0,0) 100%)",
    });
    this.#layer = new FoldLayer();
    host.append(this.base, this.#gutter, this.#layer.root);
    host.hidden = true;
  }

  /** A turn is on screen (being dragged, playing, or ended and not yet
   *  cleared). */
  get active(): boolean {
    return this.#turn != null;
  }

  /** The turn is being played to its end (not under a finger). */
  get playing(): boolean {
    return this.#frame != null && this.#drag == null;
  }

  /** p of the turn on screen, for probes. */
  get progress(): number | null {
    return this.#turn?.p ?? null;
  }

  /**
   * Sets up a sheet to turn. `clipToSheet`: nothing of the turn shows
   * outside the sheet (a single page: what goes past the spine is gone);
   * otherwise the host clips (a spread: the flap lands on the facing page).
   */
  setSheet(sheet: CurlSheet, clipToSheet: boolean, gutterX: number | null) {
    this.#sheet = sheet;
    this.#layer.setSheet(sheet, clipToSheet);
    this.#layer.setFront(sheet.front);
    this.#gutter.hidden = gutterX == null;
    if (gutterX != null) this.#gutter.style.left = `${gutterX}px`;
    this.#gutter.style.opacity = "0";
  }

  /** A client point in the sheet's frame (spine at x = 0). */
  toLocal(clientX: number, clientY: number): Point {
    const r = this.#host.getBoundingClientRect();
    const s = this.#sheet;
    if (!s) return { x: 0, y: 0 };
    const x = clientX - r.left - s.left;
    return { x: s.mirror ? s.width - x : x, y: clientY - r.top - s.top };
  }

  /** Starts a turn: the sheet is shown lying flat (forward) or turned
   *  over (back). cy: the edge the sheet is held by — 0 its top corner,
   *  its height the bottom one. */
  begin(dir: CurlDirection, cy: number) {
    this.#stop();
    const from = dir < 0 ? 1 : 0;
    this.#turn = { dir, cy, from, P: null, p: from };
    this.#host.hidden = false;
    this.#draw(this.#point(from, 0), from);
  }

  /** A finger takes hold of the sheet at a local point. */
  grab(x: number, y: number, t: number) {
    const turn = this.#turn;
    const s = this.#sheet;
    if (!turn || !s) return;
    const at = { x, y, t };
    this.#drag = { x0: x, y0: y, last: at, prev: at, lead: null, yDev: 0 };
    if (turn.dir < 0 && !s.spread) {
      this.#drag.lead = performance.now();
      this.#frame = requestAnimationFrame(() => this.#followFrame());
    }
  }

  /** The finger moved. */
  follow(x: number, y: number, t: number) {
    const d = this.#drag;
    if (!d) return;
    d.prev = d.last;
    d.last = { x, y, t };
    this.#followFrame();
  }

  #followFrame() {
    const d = this.#drag;
    const turn = this.#turn;
    const s = this.#sheet;
    if (!d || !turn || !s) return;
    const lead = d.lead == null ? null : performance.now() - d.lead;
    const p = dragProgress({
      dir: turn.dir,
      spread: s.spread,
      width: s.width,
      x0: d.x0,
      dx: d.last.x - d.x0,
      leadElapsed: lead,
    });
    d.yDev = (d.last.y - d.y0) * 0.5;
    this.#draw(this.#point(p, d.yDev), p);
    if (this.#frame != null) cancelAnimationFrame(this.#frame);
    this.#frame =
      lead != null && lead < LEAD_MS
        ? requestAnimationFrame(() => this.#followFrame())
        : null;
  }

  /** The finger let go: the turn goes over or falls back, by where the
   *  sheet is and how fast it was moving. Resolves to whether the sheet
   *  went over to the other side from where it started. */
  release(): Promise<boolean> {
    const d = this.#drag;
    const turn = this.#turn;
    const s = this.#sheet;
    this.#drag = null;
    if (this.#frame != null) cancelAnimationFrame(this.#frame);
    this.#frame = null;
    if (!d || !turn || !s) return Promise.resolve(false);
    // px/ms in the sheet's frame; + is away from the spine.
    const v = (d.last.x - d.prev.x) / Math.max(1, d.last.t - d.prev.t);
    const over = releasesOver(turn.dir, turn.p, v, s.spread);
    const target = over ? 1 : 0;
    return this.#animate(target).then(() => target !== turn.from);
  }

  /** Plays a whole turn (a tap, a key): from the bottom corner, over. */
  play(): Promise<boolean> {
    const turn = this.#turn;
    if (!turn) return Promise.resolve(false);
    return this.#animate(turn.from ? 0 : 1).then(() => true);
  }

  /** A turn being played ends now, at its last frame. */
  settle() {
    this.#settle?.();
  }

  /** Takes the turn off the screen, and its pages out of the document. */
  clear() {
    this.#stop();
    this.#turn = null;
    this.#drag = null;
    this.#host.hidden = true;
    this.#gutter.style.opacity = "0";
    this.base.replaceChildren();
    this.#layer.clear();
  }

  destroy() {
    this.clear();
    this.base.remove();
    this.#gutter.remove();
    this.#layer.root.remove();
  }

  #stop() {
    if (this.#frame != null) cancelAnimationFrame(this.#frame);
    this.#frame = null;
    this.#settle = null;
  }

  #point(p: number, yDev: number): Point {
    const s = this.#sheet!;
    return pointAt(p, yDev, s.width, s.height, this.#turn!.cy);
  }

  #animate(p1: number): Promise<void> {
    const turn = this.#turn!;
    const s = this.#sheet!;
    return new Promise((resolve) => {
      const run = runFold({
        width: s.width,
        height: s.height,
        cy: turn.cy,
        from: turn.P,
        p0: turn.p,
        p1,
        draw: (P, p) => this.#draw(P, p),
        frame: (id) => (this.#frame = id),
        done: () => {
          this.#stop();
          resolve();
        },
      });
      this.#settle = () => run.finish();
    });
  }

  #draw(P: Point, p: number) {
    const turn = this.#turn!;
    const s = this.#sheet!;
    turn.P = P;
    turn.p = p;
    const fold = this.#layer.draw(P, p, turn.cy);
    if (!fold) {
      this.#gutter.style.opacity = "0";
      return;
    }
    // A spread's gutter darkens only once the sheet stands up at the
    // spine: while just a corner is lifted the paper there lies flat.
    if (s.spread) {
      const up = Math.max(0, Math.min(1, 1 - fold.nearest / (s.width * 0.45)));
      this.#gutter.style.opacity = (strength(p) * up * up).toFixed(3);
    }
  }
}

// ------------------------------------------------------------- motion

/**
 * Where a finger has brought a sheet: the whole turn is the finger's way
 * from where it took hold (x0, in the sheet's frame) to the far side —
 * the spine of a single page, the facing page's outer edge on a spread.
 * A single sheet brought back first comes over by itself as far as LEAD
 * (`leadElapsed`: ms since the finger took hold; null: no lead), and the
 * finger takes it from there. Held short of the far side (`held`).
 */
export function dragProgress(o: {
  dir: CurlDirection;
  spread: boolean;
  width: number;
  x0: number;
  /** The finger's way so far along the sheet's x (+ away from the spine). */
  dx: number;
  leadElapsed: number | null;
}): number {
  const { dir, spread, width: W, x0, dx, leadElapsed } = o;
  let from = dir < 0 ? 1 : 0;
  const lead = leadElapsed != null;
  if (lead) {
    const t = Math.min(1, leadElapsed / LEAD_MS);
    const e = 1 - Math.pow(1 - t, 3);
    from = 1 + (LEAD - 1) * e;
  }
  const span = Math.max(W * 0.25, dir > 0 ? x0 + (spread ? W : 0) : W - x0);
  const dp = (-dx / span) * (lead ? LEAD : 1);
  return held(from + dp, spread, dir);
}

/** Whether a sheet let go `p` of the way over, the finger moving at `v`
 *  (px/ms in the sheet's frame, + away from the spine), goes over. */
export function releasesOver(
  dir: CurlDirection,
  p: number,
  v: number,
  spread: boolean,
): boolean {
  return dir > 0
    ? (p > 0.3 || v < -0.35) && v < 0.35
    : !((p < (spread ? 0.7 : 0.88) || v > 0.35) && v > -0.35);
}

/** How long a turn takes from p0 to p1 without the finger, on a sheet
 *  `width` wide. */
export function foldMs(p0: number, p1: number, width: number): number {
  return (260 + 380 * Math.abs(p1 - p0)) * (1 + 0.6 * wideness(width));
}

/** 0 for a phone-sized sheet, 1 for one four times as wide or more. */
function wideness(width: number): number {
  return Math.min(1, (Math.sqrt(Math.max(1, width / PHONE_WIDTH)) - 1) / 0.6);
}

/** Where a turn is `t` of its time along. A phone's sheet leaves at
 *  speed and settles; a wide one, set off from lying flat, gathers speed
 *  first, or its corner is across the window before the eye is on it. */
function foldEase(t: number, fromFlat: boolean, width: number): number {
  const out = 1 - Math.pow(1 - t, 3);
  if (!fromFlat) return out;
  const both = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const w = wideness(width);
  return out + (both - out) * w;
}

/**
 * Plays a sheet from where it is to p1 (0 flat, 1 over) along the low
 * arc; let go mid-drag, the finger's height above that arc is given up
 * early in the run, so the fold turns as the sheet travels instead of
 * sliding across with it. `from`: the corner's point now (null: on the
 * arc at p0). `finish` jumps to the end; `cancel` stops where it is.
 */
export function runFold(o: {
  width: number;
  height: number;
  cy: number;
  from: Point | null;
  p0: number;
  p1: number;
  draw: (P: Point, p: number) => void;
  /** The animation frame requested, for the caller to cancel. */
  frame?: (id: number | null) => void;
  done: () => void;
}): { finish: () => void; cancel: () => void } {
  const { width: W, height: H, cy, p1 } = o;
  let p0 = o.p0;
  let yDev0 = 0;
  if (o.from) {
    p0 = Math.max(0, Math.min(1, (W - o.from.x) / (2 * W)));
    const base = cy + (cy > H / 2 ? -arcLift(p0, H) : arcLift(p0, H));
    yDev0 = o.from.y - base;
  }
  const dur = foldMs(p0, p1, W);
  const fromFlat = Math.min(p0, 1 - p0) < 0.02;
  const t0 = performance.now();
  let id: number | null = null;
  let over = false;
  const stop = () => {
    over = true;
    if (id != null) cancelAnimationFrame(id);
    id = null;
    o.frame?.(null);
  };
  const end = () => {
    if (over) return;
    stop();
    o.draw(pointAt(p1, 0, W, H, cy), p1);
    o.done();
  };
  const step = (now: number) => {
    if (over) return;
    // (A frame's time is when the frame began, which can be just before
    // the run did.)
    const t = Math.max(0, Math.min(1, (now - t0) / dur));
    if (t >= 1) return end();
    const e = foldEase(t, fromFlat, W);
    const q = Math.min(1, t / 0.55);
    const settle = 1 - (1 - q) * (1 - q);
    const p = p0 + (p1 - p0) * e;
    o.draw(pointAt(p, yDev0 * (1 - settle), W, H, cy), p);
    id = requestAnimationFrame(step);
    o.frame?.(id);
  };
  id = requestAnimationFrame(step);
  o.frame?.(id);
  return { finish: end, cancel: stop };
}
