// A round opening onto an element that covers the screen: it grows from
// a point until the element is all there is, or closes down to nothing.
// A rim of lamplight goes round its edge.
//
// Given a pool (a round patch of colour already on the page, about the
// same point), the opening is that pool growing: a band of its colour,
// as wide as the pool was, goes out ahead of the opening and takes the
// page with it. Closing, it comes back to be the pool again.

export interface Pool {
  radius: number;
  color: string;
}

const ease = (t: number) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2);

export function iris(
  el: HTMLElement,
  open: boolean,
  ms: number,
  at = { x: innerWidth / 2, y: innerHeight / 2 },
  pool?: Pool,
) {
  const rim = document.createElement("div");
  rim.setAttribute("aria-hidden", "true");
  rim.style.cssText =
    `position:fixed;left:${at.x}px;top:${at.y}px;z-index:61;` +
    "border-radius:50%;pointer-events:none;" +
    "transform:translate(-50%,-50%);" +
    "box-shadow:0 0 0 2px rgba(255,236,200,.9),0 0 38px 12px rgba(255,205,130,.55)," +
    "inset 0 0 30px 8px rgba(255,205,130,.4)";
  document.body.appendChild(rim);
  // Under the element (z 60), over the page.
  const band = pool ? document.createElement("div") : null;
  if (band && pool) {
    band.setAttribute("aria-hidden", "true");
    band.style.cssText =
      `position:fixed;left:${at.x}px;top:${at.y}px;z-index:58;` +
      "border-radius:50%;pointer-events:none;" +
      `transform:translate(-50%,-50%);background:${pool.color}`;
    document.body.appendChild(band);
  }
  const full =
    Math.hypot(
      Math.max(at.x, innerWidth - at.x),
      Math.max(at.y, innerHeight - at.y),
    ) + 24;
  const where = `${at.x.toFixed(1)}px ${at.y.toFixed(1)}px`;
  return new Promise<void>((done) => {
    const t0 = performance.now();
    const tick = () => {
      const t = Math.min(1, (performance.now() - t0) / ms);
      const e = ease(t);
      const r = full * (open ? e : 1 - e);
      el.style.clipPath = `circle(${r.toFixed(1)}px at ${where})`;
      rim.style.width = rim.style.height = `${(r * 2).toFixed(1)}px`;
      if (band && pool)
        band.style.width =
          band.style.height = `${((r + pool.radius) * 2).toFixed(1)}px`;
      // The rim is brightest as the opening is small.
      rim.style.opacity = String(Math.min(1, 1.25 - r / full));
      if (t < 1) return requestAnimationFrame(tick);
      rim.remove();
      band?.remove();
      el.style.clipPath = open ? "none" : `circle(0px at ${where})`;
      done();
    };
    tick();
  });
}
