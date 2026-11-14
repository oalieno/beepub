// The way into a book and out of it again.
//
// From the bookshelf, reading a book is going in through its page: the
// page's light swells until it is everything, lines of it streaming past,
// and the reader comes into view out of that light. Leaving the reader is
// the same road backward, ending with the book open in hand.
//
// It is one canvas on the body, above everything, so it stays up while
// the page under it changes. Nothing here knows about three.js: the
// reader loads this without loading the bookshelf.

type RGB = [number, number, number];
export interface Point {
  x: number;
  y: number;
}

const PAPER: RGB = [236, 224, 198]; // the page of the book in hand
const LIGHT: RGB = [255, 255, 255]; // the reader's page
const DARK: RGB = [23, 19, 16]; // the reader's page at night

export const DIVE_MS = 1350;
export const SURFACE_MS = 1200;
/** The dive holds its breath for this much of its length before it goes. */
const BREATH = 0.16;
/** How far in (0..1) the dive is, a share `t` of the way through it. */
export function diveAmount(t: number) {
  return t < BREATH ? 0 : (t - BREATH) / (1 - BREATH);
}
/** The same for coming back out: 1 down to 0, slowing as it arrives. */
export function surfaceAmount(t: number) {
  return (1 - t) ** 1.7;
}
/** How large the book is seen (1: as it lies open) that far in. */
export function scaleAt(amount: number) {
  return 5.5 ** (amount ** 2.4);
}
/** How far the page gone in through has come to the middle of the screen
 *  (0: where it lies, 1: the middle) — there before the light is all. */
export function driftAt(amount: number) {
  return smooth(0, 0.7, amount);
}
/** The small step back before the dive. */
export function breathAt(t: number) {
  return t < BREATH ? 1 - 0.035 * Math.sin((Math.PI / 2) * (t / BREATH)) : null;
}

export const still = () =>
  typeof matchMedia !== "undefined" &&
  matchMedia("(prefers-reduced-motion: reduce)").matches;

const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};
const mix = (a: RGB, b: RGB, t: number): RGB => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
];
const rgba = (c: RGB, a: number) =>
  `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
const lum = (c: RGB) => (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;

interface Streak {
  a: number; // its bearing from the middle
  r: number; // how far out, as a share of the way to the far corner
  z: number; // how fast it is, beside the others
  o: number; // how bright
  c: number; // which of the colours
}
const FAR = 1.2;
const NEAR = 0.012;
const COUNT = 230;

let canvas: HTMLCanvasElement | null = null;
let ctx: CanvasRenderingContext2D | null = null;
let raf = 0;
let last = 0;
let run = 0; // the movement now playing; a newer one ends an older
let failsafe: ReturnType<typeof setTimeout> | undefined;
let covered = false;
let streaks: Streak[] = [];

// What is drawn.
let cx = 0;
let cy = 0;
let amount = 0; // the light from the page: nothing .. everything
let flat = 0; // the whole screen one colour
let hole = 0; // an opening in that, from the middle outward
let speed = 0; // of the lines; below zero they fall inward
let lines = 0; // how much the lines show
let tone: RGB = PAPER;
let toneTo: RGB = PAPER;
let palette: RGB[] = [PAPER, PAPER, PAPER, PAPER, PAPER];

/** The bookshelf a reader was entered from, to come back out at. */
let origin: { id: string; href: string } | null = null;

function seed() {
  streaks = Array.from({ length: COUNT }, () => ({
    a: Math.random() * Math.PI * 2,
    // Even along the way out, as lines flying past at a steady rate are.
    r: Math.exp(
      Math.log(NEAR) + Math.random() * (Math.log(FAR) - Math.log(NEAR)),
    ),
    z: 0.55 + Math.random() * 0.9,
    o: 0.35 + Math.random() * 0.65,
    c: (Math.random() * 5) | 0,
  }));
}

function size() {
  if (!canvas) return;
  const dpr = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(innerWidth * dpr);
  canvas.height = Math.round(innerHeight * dpr);
  ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function up() {
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.dataset.testid = "shelf-portal";
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText =
      "position:fixed;inset:0;width:100%;height:100%;z-index:200;touch-action:none";
    ctx = canvas.getContext("2d");
    addEventListener("resize", size);
    seed();
  }
  if (!canvas.isConnected) document.body.appendChild(canvas);
  canvas.hidden = false;
  size();
  if (!raf) {
    last = performance.now();
    raf = requestAnimationFrame(frame);
  }
}

function down() {
  cancelAnimationFrame(raf);
  raf = 0;
  clearTimeout(failsafe);
  covered = false;
  amount = flat = hole = lines = 0;
  if (canvas) {
    canvas.hidden = true;
    canvas.dataset.state = "idle";
    ctx!.clearRect(0, 0, innerWidth, innerHeight);
  }
}

function frame(now: number) {
  raf = requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  // The colour of the light goes over to the page that is coming.
  const k = 1 - Math.exp(-dt * 7);
  tone = mix(tone, toneTo, k);
  for (const s of streaks) {
    s.r *= Math.exp(speed * s.z * dt);
    if (s.r > FAR) {
      s.r = NEAR * (1 + Math.random() * 3);
      s.a = Math.random() * Math.PI * 2;
    } else if (s.r < NEAR) {
      s.r = FAR * (0.75 + Math.random() * 0.25);
      s.a = Math.random() * Math.PI * 2;
    }
  }
  draw();
}

function draw() {
  const g = ctx!;
  const w = innerWidth;
  const h = innerHeight;
  g.globalCompositeOperation = "source-over";
  g.clearRect(0, 0, w, h);
  const far = Math.hypot(Math.max(cx, w - cx), Math.max(cy, h - cy));

  if (amount > 0 && flat < 1) {
    const r = far * (0.03 + 2.7 * amount ** 3.2);
    const grad = g.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, rgba(tone, Math.min(1, amount * 4)));
    grad.addColorStop(0.5, rgba(tone, 0.92 * Math.min(1, amount * 2.4)));
    grad.addColorStop(1, rgba(tone, 0));
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
  }
  if (flat > 0) {
    g.fillStyle = rgba(tone, flat);
    g.fillRect(0, 0, w, h);
  }

  if (lines > 0.004) {
    // On the way in, lines in the book's own colours, seen against the
    // dark room and the light page alike; once the screen is all light,
    // a faint thread of them is left.
    const onTone: RGB = lum(tone) > 0.5 ? [70, 54, 36] : [241, 232, 216];
    const tail = Math.min(0.6, Math.abs(speed) * 0.065 + 0.012);
    const dir = Math.sign(speed || 1);
    g.lineCap = "round";
    for (const s of streaks) {
      const a = lines * s.o * Math.min(1, s.r / 0.07) * (0.85 - 0.63 * flat);
      if (a < 0.01) continue;
      const r0 = s.r * Math.exp(-dir * tail * s.z);
      const cos = Math.cos(s.a);
      const sin = Math.sin(s.a);
      g.strokeStyle = rgba(mix(palette[s.c], onTone, flat), a);
      g.lineWidth = 0.8 + 4.2 * Math.min(1, s.r) * s.z;
      g.beginPath();
      g.moveTo(cx + cos * r0 * far, cy + sin * r0 * far);
      g.lineTo(cx + cos * s.r * far, cy + sin * s.r * far);
      g.stroke();
    }
  }

  if (hole > 0) {
    g.globalCompositeOperation = "destination-out";
    const r = far * 1.6 * hole;
    const grad = g.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, "rgba(0,0,0,1)");
    grad.addColorStop(0.68, "rgba(0,0,0,1)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
    g.globalCompositeOperation = "source-over";
  }
}

/** Plays `step` over `ms`; resolves false if another movement took over. */
function play(ms: number, step: (t: number) => void) {
  const mine = ++run;
  return new Promise<boolean>((done) => {
    const t0 = performance.now();
    const tick = () => {
      if (mine !== run) return done(false);
      const t = Math.min(1, (performance.now() - t0) / ms);
      step(t);
      if (t < 1) requestAnimationFrame(tick);
      else done(true);
    };
    tick();
  });
}

function hold(state: string) {
  covered = true;
  amount = flat = 1;
  hole = 0;
  canvas!.dataset.state = state;
  // Never a screen left covered: whatever was to come and lift this, if
  // it has not, it lifts by itself.
  clearTimeout(failsafe);
  failsafe = setTimeout(() => void arrive(), 12_000);
}

function colours(tint: RGB) {
  // The book's cloth, lighter and darker; the gilt of its lettering; ink;
  // the white of the page.
  palette = [
    tint,
    mix(tint, [255, 255, 255], 0.45),
    mix(tint, [20, 14, 8], 0.35),
    [214, 168, 92],
    [255, 246, 228],
  ];
}

const middle = () => {
  cx = innerWidth / 2;
  cy = innerHeight / 2;
};

/** In through the page at `at`. Ends with the screen all light, and
 *  stays so until `arrive`. */
async function dive(at: Point, tint: RGB) {
  up();
  const aim = (u: number) => {
    const d = driftAt(u);
    cx = at.x + (innerWidth / 2 - at.x) * d;
    cy = at.y + (innerHeight / 2 - at.y) * d;
  };
  aim(0);
  colours(tint);
  tone = toneTo = PAPER;
  hole = 0;
  canvas!.dataset.state = "dive";
  if (still()) {
    await play(220, (t) => {
      amount = 0;
      flat = t;
      lines = 0;
    });
  } else {
    await play(DIVE_MS, (t) => {
      const u = diveAmount(t);
      aim(u);
      amount = u;
      flat = smooth(0.72, 1, u);
      speed = 0.5 + 11 * u ** 3;
      lines = smooth(0.02, 0.4, t);
    });
    speed = 1.5;
    lines = 0.9;
  }
  hold("travel");
}

/** The reader is there (not yet its page): the light turns to its colour. */
function landing(dark: boolean) {
  if (covered) toneTo = dark ? DARK : LIGHT;
}

/** The page is there: the light opens from the middle onto it. */
async function arrive() {
  if (!covered) return;
  covered = false;
  clearTimeout(failsafe);
  middle();
  canvas!.dataset.state = "arrive";
  const from = speed;
  const done = await play(still() ? 220 : 900, (t) => {
    if (still()) {
      flat = 1 - t;
      amount = 0;
      return;
    }
    const e = t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
    hole = e;
    lines = 0.9 * (1 - t);
    speed = from * (1 - 0.8 * t);
  });
  if (done) down();
}

/** Out of the reader: its page closes in to the middle, and the screen
 *  is held until the bookshelf has the book ready (`surface`). */
async function leave(dark: boolean) {
  up();
  middle();
  tone = toneTo = dark ? DARK : LIGHT;
  amount = flat = 1;
  hole = 1;
  canvas!.dataset.state = "leave";
  await play(still() ? 200 : 620, (t) => {
    if (still()) {
      hole = 0;
      flat = t;
      return;
    }
    hole = (1 - t) ** 3;
    lines = 0.9 * t;
    speed = -(1 + 5 * t);
  });
  speed = -1.5;
  lines = still() ? 0 : 0.9;
  toneTo = PAPER;
  hold("travel");
}

/** Covered at once, with no way in played (the browser's own Back). */
function snap() {
  up();
  middle();
  tone = toneTo = PAPER;
  speed = -1.5;
  lines = still() ? 0 : 0.9;
  run++;
  hold("travel");
}

/** Back out through the page at `at`: the light draws in to it and is
 *  gone, the book open in hand. */
async function surface(at: Point, tint: RGB) {
  if (!covered) return;
  covered = false;
  clearTimeout(failsafe);
  middle();
  colours(tint);
  toneTo = PAPER;
  canvas!.dataset.state = "surface";
  const done = await play(still() ? 220 : SURFACE_MS, (t) => {
    if (still()) {
      amount = 0;
      flat = 1 - t;
      return;
    }
    const u = surfaceAmount(t);
    const d = driftAt(u);
    cx = at.x + (innerWidth / 2 - at.x) * d;
    cy = at.y + (innerHeight / 2 - at.y) * d;
    amount = u;
    flat = smooth(0.72, 1, u);
    speed = -(0.4 + 9 * u ** 3);
    lines = smooth(0, 0.3, u);
  });
  if (done) down();
}

export const portal = {
  dive,
  landing,
  arrive,
  leave,
  snap,
  surface,
  get covered() {
    return covered;
  },
  get origin() {
    return origin;
  },
  set origin(o: { id: string; href: string } | null) {
    origin = o;
  },
};
