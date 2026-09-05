import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  TOUCH_BOOK,
  VERTICAL_LONG_BOOK,
  seedFixture,
  type Fixture,
} from "./ng-helpers";

/**
 * reader-ng G0 kill point, promoted from e2e/probes/ng-geometry.mjs.
 *
 * The new engine keeps position as an intent (the visible Range at the
 * last user page turn) and re-derives it after every layout change. For
 * each geometry input we assert, after the reflow settles:
 *   (a) that anchor is still inside the visible range,
 *   (b) no text rect is cut by the page box on the pagination axis (no
 *       neighbouring page peeking in),
 *   (c) the iframe stepped through at most one intermediate size.
 * (The probe additionally screencasts to show the intermediate size never
 * paints; that stays a probe — CDP-only and slow.)
 */

const BOOKS: { name: string; fixture: Fixture; font: string }[] = [
  {
    name: "vertical-rl",
    fixture: VERTICAL_LONG_BOOK,
    // Noto Sans CJK TC is the CJK face the e2e hosts have; the serif stack
    // would fall back to glyphs with a zero vertical advance.
    font: "sans",
  },
  { name: "horizontal", fixture: TOUCH_BOOK, font: "serif" },
];

// One reflow per step. Layout params go straight to the engine (the
// same call BookReader makes); font size and line height go through the
// settings sheet, the product path; the last step shrinks the viewport —
// the container-size change hiding or pinning a bar would make.
const STEPS: (
  | { name: string; layout: Record<string, number> }
  | { name: string; sheet: string }
  | { name: string; viewport: number }
)[] = [
  { name: "gap 24→64px", layout: { gap: 64 } },
  { name: "margin 48→16px", layout: { margin: 16 } },
  { name: "font 18→20px", sheet: "Increase font size" },
  { name: "line-height 1.8→2.2", sheet: "Relaxed" },
  { name: "viewport −48px", viewport: -48 },
];

test.use({ storageState: ADMIN_STATE });

declare global {
  interface Window {
    __beepubReaderNG?: any;
    __ngAnchor?: Range | null;
    __ngWatch?: any;
  }
}

async function openNg(page: Page, bookId: string, font: string) {
  const params = new URLSearchParams({
    size: "18",
    lh: "1.8",
    mx: "24",
    my: "48",
    font,
  });
  await page.goto(`/books/${bookId}/read-ng?${params}`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  // Page in so the anchor is a user-driven visible range (reason 'page').
  for (let i = 0; i < 3; i++) {
    await page.evaluate(() => window.__beepubReaderNG.core.next());
    await page.waitForTimeout(250);
  }
  await expect
    .poll(() =>
      page.evaluate(() => window.__beepubReaderNG.core.lastLocation.reason),
    )
    .toBe("page");
  await page.evaluate(() => {
    const loc = window.__beepubReaderNG.core.lastLocation;
    window.__ngAnchor = loc.range ? loc.range.cloneRange() : null;
  });
}

/** Visible text rects vs the scroll container (the box that clips). */
function snapshot(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const frame = doc.defaultView!.frameElement as HTMLIFrameElement;
    const box = frame.parentElement!.parentElement!.getBoundingClientRect();
    const fb = frame.getBoundingClientRect();
    const vertical: boolean = core.vertical;
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    let vis = 0;
    let cut = 0;
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (!n.textContent?.trim()) continue;
      const rg = doc.createRange();
      rg.selectNodeContents(n);
      for (const r of rg.getClientRects()) {
        if (r.width <= 0 || r.height <= 0) continue;
        const top = r.top + fb.top;
        const bottom = r.bottom + fb.top;
        const left = r.left + fb.left;
        const right = r.right + fb.left;
        const inside =
          bottom > box.top + 1 &&
          top < box.bottom - 1 &&
          right > box.left + 1 &&
          left < box.right - 1;
        if (!inside) continue;
        vis++;
        const cutHere = vertical
          ? top < box.top - 1 || bottom > box.bottom + 1
          : left < box.left - 1 || right > box.right + 1;
        if (cutHere) cut++;
      }
    }
    // The anchor is on screen when the rect of its first character (or the
    // first rect of an element anchor) sits inside the clipping box on the
    // pagination axis. Boundary-point comparison would be too strict: the
    // visible range starts at (p, 0) while the paragraph fits the page and
    // at (text, 0) once it spans two — the same place, different points.
    const loc = core.lastLocation;
    const a = window.__ngAnchor;
    let anchorHeld: boolean | null = null;
    if (a && a.startContainer.ownerDocument === doc) {
      const node = a.startContainer;
      const off = a.startOffset;
      const r = doc.createRange();
      const max =
        node.nodeType === 3 ? (node as Text).length : node.childNodes.length;
      if (off < max) {
        r.setStart(node, off);
        r.setEnd(node, off + 1);
      } else r.selectNodeContents(node);
      const rect = Array.from(r.getClientRects()).find(
        (x) => x.width > 0 && x.height > 0,
      );
      if (rect) {
        const mid = vertical
          ? (rect.top + rect.bottom) / 2 + fb.top
          : (rect.left + rect.right) / 2 + fb.left;
        const [lo, hi] = vertical
          ? [box.top, box.bottom]
          : [box.left, box.right];
        anchorHeld = mid >= lo && mid <= hi;
      }
    }
    return { vis, cut, anchorHeld, reason: loc?.reason as string };
  });
}

async function armWatch(page: Page) {
  await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const frame = doc.defaultView!.frameElement as HTMLIFrameElement;
    const axis = core.vertical ? "height" : "width";
    const w: { sizes: number[]; done: boolean; stop?: () => void } = {
      sizes: [],
      done: false,
    };
    const sample = () => {
      const s = Math.round(frame.getBoundingClientRect()[axis]);
      if (w.sizes.at(-1) !== s) w.sizes.push(s);
      if (!w.done) requestAnimationFrame(sample);
    };
    sample();
    w.stop = () => (w.done = true);
    window.__ngWatch = w;
  });
}

async function settle(page: Page): Promise<number[]> {
  let last = "";
  let lastChange = Date.now();
  const t0 = Date.now();
  while (Date.now() - t0 < 5000) {
    await page.waitForTimeout(100);
    const cur = await page.evaluate(() =>
      JSON.stringify(window.__ngWatch.sizes),
    );
    if (cur !== last) {
      last = cur;
      lastChange = Date.now();
    } else if (Date.now() - lastChange > 600) break;
  }
  return page.evaluate(() => {
    window.__ngWatch.stop();
    return window.__ngWatch.sizes as number[];
  });
}

for (const book of BOOKS) {
  test(`reader-ng keeps the anchor and page grid through layout changes (${book.name})`, async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, book.fixture);
    await openNg(page, bookId, book.font);

    const baseline = await snapshot(page);
    expect(baseline.vis, "baseline has visible text").toBeGreaterThan(0);
    expect(baseline.cut, "baseline: no rect cut by the page box").toBe(0);

    for (const step of STEPS) {
      await armWatch(page);
      if ("layout" in step) {
        await page.evaluate(
          (l) => window.__beepubReaderNG.core.setLayout(l),
          step.layout,
        );
      } else if ("sheet" in step) {
        await page.getByRole("button", { name: "Reader settings" }).click();
        await page.getByRole("button", { name: step.sheet }).click();
        await page.keyboard.press("Escape");
      } else {
        const size = page.viewportSize()!;
        await page.setViewportSize({
          width: size.width,
          height: size.height + step.viewport,
        });
      }
      const sizes = await settle(page);
      const after = await snapshot(page);
      expect(
        after.reason,
        `${step.name}: reflow relocated from the anchor`,
      ).toBe("anchor");
      expect(after.vis, `${step.name}: visible text`).toBeGreaterThan(0);
      expect(after.cut, `${step.name}: no rect cut by the page box`).toBe(0);
      expect(after.anchorHeld, `${step.name}: anchor still in view`).toBe(true);
      expect(
        sizes.length,
        `${step.name}: iframe size steps ${sizes.join("→")}`,
      ).toBeLessThanOrEqual(3);
    }
  });
}
