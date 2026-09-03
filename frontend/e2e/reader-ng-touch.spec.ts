import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  test,
  expect,
  devices,
  type APIRequestContext,
  type CDPSession,
  type Page,
} from "@playwright/test";
import { ADMIN_STATE, LIBRARY_NAME } from "./helpers";

/**
 * reader-ng G1: the gesture layer on the new engine, on an emulated
 * iPhone (the reader's iOS paths are UA-gated; CDP dispatches trusted
 * touch input including the browser's own click synthesis).
 *
 * Covers what G1 owns — edge tap zones, swipe, tap-to-toggle chrome — and
 * re-runs the iOS highlight-menu flicker regressions (b27e913, d09d440)
 * against read-ng. Saved-highlight (mark) cases arrive with G2.
 */

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-touch-book.epub",
);
const BOOK_TITLE = "Flicker Repro Book";

const { defaultBrowserType: _webkit, ...iphone } = devices["iPhone 13"];
test.use({ storageState: ADMIN_STATE, ...iphone });

declare global {
  interface Window {
    __beepubReaderNG?: any;
    __menuLog?: string[];
    __menuT0?: number;
    __menuFrames?: { left: string; l: number; r: number }[];
  }
}

async function seedBook(request: APIRequestContext): Promise<string> {
  const libraries = await (await request.get("/api/libraries")).json();
  const library = libraries.find(
    (l: { name: string }) => l.name === LIBRARY_NAME,
  );
  expect(library).toBeTruthy();
  const books = await (
    await request.get(`/api/libraries/${library.id}/books?limit=100`)
  ).json();
  const existing = books.items?.find((b: Record<string, string>) =>
    (b.display_title ?? b.epub_title ?? "").includes(BOOK_TITLE),
  );
  if (existing) return existing.id;
  const uploaded = await request.post("/api/books", {
    multipart: {
      file: {
        name: "e2e-touch-book.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(FIXTURE),
      },
      library_id: library.id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  return (await uploaded.json()).id;
}

async function openBook(
  page: Page,
  bookId: string,
  overrides: Record<string, string> = {},
) {
  // panel=0: the geometry instrument would sit over the lower right.
  const params = new URLSearchParams({
    size: "18",
    lh: "1.8",
    gap: "7",
    margin: "48",
    cols: "1",
    panel: "0",
    ...overrides,
  });
  await page.goto(`/books/${bookId}/read-ng?${params}`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await expect
    .poll(() =>
      page.evaluate(() => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        return doc.body?.textContent?.includes("starship librarian") ?? false;
      }),
    )
    .toBe(true);
  await page.waitForTimeout(500);
}

function location(page: Page) {
  return page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return {
      index: l.index as number,
      fraction: l.fraction as number,
      reason: l.reason as string,
    };
  });
}

async function armMenuWatcher(page: Page) {
  await page.evaluate(() => {
    window.__menuLog = [];
    window.__menuT0 = performance.now();
    let visible = !!document.querySelector('[data-testid="highlight-menu"]');
    new MutationObserver(() => {
      const v = !!document.querySelector('[data-testid="highlight-menu"]');
      if (v === visible) return;
      visible = v;
      window.__menuLog!.push(
        `${Math.round(performance.now() - window.__menuT0!)}ms ${v ? "SHOW" : "HIDE"}`,
      );
    }).observe(document.body, { childList: true, subtree: true });
  });
}

function menuTimeline(page: Page): Promise<string[]> {
  return page.evaluate(() => window.__menuLog ?? []);
}

async function touchTap(
  cdp: CDPSession,
  pt: { x: number; y: number },
  holdMs: number,
) {
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: pt.x, y: pt.y }],
  });
  await new Promise((resolve) => setTimeout(resolve, holdMs));
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
}

async function swipe(
  cdp: CDPSession,
  from: { x: number; y: number },
  to: { x: number; y: number },
) {
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: from.x, y: from.y }],
  });
  for (const f of [0.25, 0.5, 0.75, 1]) {
    await new Promise((resolve) => setTimeout(resolve, 30));
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        { x: from.x + (to.x - from.x) * f, y: from.y + (to.y - from.y) * f },
      ],
    });
  }
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
}

/** Viewport point of a word inside the section iframe (nth occurrence).
 *  The iframe lives in a closed shadow root: reach it through the engine. */
async function pointOnWord(page: Page, word: string, occurrence: number) {
  return page.evaluate(
    ([word, occurrence]) => {
      const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
      const io = (
        doc.defaultView!.frameElement as HTMLIFrameElement
      ).getBoundingClientRect();
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      let hits = 0;
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const idx = (node.textContent ?? "").indexOf(word as string);
        if (idx < 0 || hits++ < (occurrence as number)) continue;
        const range = doc.createRange();
        range.setStart(node, idx + 1);
        range.setEnd(node, idx + (word as string).length - 1);
        const rect = range.getBoundingClientRect();
        return {
          x: io.left + rect.left + rect.width / 2,
          y: io.top + rect.top + rect.height / 2,
        };
      }
      return null;
    },
    [word, occurrence] as const,
  );
}

function overlayState(page: Page) {
  return page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const el = doc.getElementById("beepub-sel-overlay");
    const child = el?.firstElementChild;
    if (!el || !child) return null;
    return {
      opacity: getComputedStyle(el).opacity,
      fill: getComputedStyle(child).backgroundColor,
    };
  });
}

test("tap zones: left quarter back, right quarter forward, independent of the gap", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  // gap=0: no page margin at all. Tap zones used to be parent-document
  // buttons sized to the margin, so a zero margin left nothing to tap.
  await openBook(page, bookId, { gap: "0" });
  const cdp = await context.newCDPSession(page);
  const vw = await page.evaluate(() => window.innerWidth);

  const start = await location(page);
  await touchTap(cdp, { x: vw * 0.875, y: 420 }, 60);
  await expect.poll(() => location(page)).toMatchObject({ reason: "page" });
  // The paginator holds a 100ms lock after each turn (its double-tap
  // guard); a second input inside it is dropped by design.
  await page.waitForTimeout(200);
  const after = await location(page);
  expect(after.fraction > start.fraction || after.index > start.index).toBe(
    true,
  );

  await touchTap(cdp, { x: vw * 0.125, y: 420 }, 60);
  await page.waitForTimeout(400);
  const back = await location(page);
  expect(back.index).toBe(start.index);
  expect(back.fraction).toBeCloseTo(start.fraction, 3);

  // Nothing overlays the page any more: long-press selection reaches the
  // edges (covered by the selection tests) and there are no zone buttons.
  await expect(
    page.getByTestId("book-reader").getByRole("button", { name: /page/i }),
  ).toHaveCount(0);
});

test("a horizontal swipe turns the page", async ({ page, context }) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);
  const cdp = await context.newCDPSession(page);

  const start = await location(page);
  await swipe(cdp, { x: 260, y: 420 }, { x: 80, y: 420 });
  await expect.poll(() => location(page)).toMatchObject({ reason: "page" });
  // The paginator holds a 100ms lock after each turn (its double-tap
  // guard); a second input inside it is dropped by design.
  await page.waitForTimeout(200);
  const after = await location(page);
  expect(after.fraction > start.fraction || after.index > start.index).toBe(
    true,
  );

  await swipe(cdp, { x: 80, y: 420 }, { x: 260, y: 420 });
  await page.waitForTimeout(300);
  const back = await location(page);
  expect(back.index).toBe(start.index);
  expect(back.fraction).toBeCloseTo(start.fraction, 3);
});

test("a plain tap neither turns the page nor opens the menu", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);
  const cdp = await context.newCDPSession(page);
  const header = page.getByTestId("ng-chrome");
  await expect(header).toBeVisible();
  const before = await location(page);

  // Middle of the page, clear of the edge zones; a quick tap arrives as
  // touchstart + touchend + the browser's synthesized click. It reaches
  // BookReader's ontap and nothing else — in particular it must not reflow
  // the page (read-ng leaves ontap unwired: an in-flow header toggling on
  // every tap made the text jump on device).
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  await page.waitForTimeout(500);
  expect(await location(page)).toEqual(before);
  await expect(page.getByTestId("highlight-menu")).toBeHidden();
  await expect(header).toBeVisible();
});

test("long-press selection survives the synthesized click that follows", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  const pt = await pointOnWord(page, "whispering", 1);
  expect(pt).toBeTruthy();

  await armMenuWatcher(page);
  const cdp = await context.newCDPSession(page);
  // Hold well past both the 300ms long-press threshold and the menu's
  // 500ms just-shown grace, so only the click suppressor can save it.
  await touchTap(cdp, pt!, 900);
  // WebKit synthesizes a click on release even after long holds (delayed
  // up to ~350ms in iframes); emulated chromium won't here, so send the
  // equivalent trusted click through CDP.
  await page.waitForTimeout(80);
  await cdp.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: pt!.x,
    y: pt!.y,
    button: "left",
    clickCount: 1,
  });
  await cdp.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: pt!.x,
    y: pt!.y,
    button: "left",
    clickCount: 1,
  });

  await page.waitForTimeout(1200);
  expect(await menuTimeline(page)).toEqual([expect.stringMatching(/SHOW$/)]);
  await expect(page.getByTestId("highlight-menu")).toBeVisible();
  // The page did not turn under the long press.
  expect((await location(page)).reason).not.toBe("page");

  // Theme-tinted solid rects under one group opacity (light theme).
  expect(await overlayState(page)).toEqual({
    opacity: "0.3",
    fill: "rgb(196, 146, 74)",
  });
});

test("drag selection paints line fragments, not paragraph slabs", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  const from = await pointOnWord(page, "Chapter", 0);
  const to = await pointOnWord(page, "whispering", 1);
  expect(from).toBeTruthy();
  expect(to).toBeTruthy();

  const cdp = await context.newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: from!.x, y: from!.y }],
  });
  await page.waitForTimeout(450);
  for (const f of [0.25, 0.5, 0.75, 1]) {
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        {
          x: from!.x + (to!.x - from!.x) * f,
          y: from!.y + (to!.y - from!.y) * f,
        },
      ],
    });
    await page.waitForTimeout(50);
  }
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await page.waitForTimeout(500);

  const overlay = await page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const el = doc.getElementById("beepub-sel-overlay");
    if (!el) return null;
    const pEl = doc.querySelector("p")!;
    const p = pEl.getBoundingClientRect();
    return {
      rects: [...el.children].map((c) => {
        const r = c.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, height: r.height };
      }),
      paragraph: { top: p.top, bottom: p.bottom, height: p.height },
      linePitch: parseFloat(doc.defaultView!.getComputedStyle(pEl).lineHeight),
    };
  });
  expect(overlay).toBeTruthy();
  expect(overlay!.rects.length).toBeGreaterThan(3);
  for (const r of overlay!.rects) {
    expect(r.height).toBeLessThan(
      overlay!.paragraph.height - overlay!.linePitch / 2,
    );
  }
  const inParagraph = overlay!.rects
    .filter(
      (r) =>
        r.top >= overlay!.paragraph.top - 2 &&
        r.bottom <= overlay!.paragraph.bottom + 2,
    )
    .sort((a, b) => a.top - b.top);
  expect(inParagraph.length).toBeGreaterThan(2);
  for (let i = 1; i < inParagraph.length; i++) {
    expect(inParagraph[i].top - inParagraph[i - 1].bottom).toBeLessThanOrEqual(
      1,
    );
  }
  // A drag that selects must not also turn the page.
  expect((await location(page)).reason).not.toBe("page");
});

test("menu opened near the screen edge is clamped from the first frame", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  await page.evaluate(() => {
    window.__menuFrames = [];
    const sample = () => {
      const el = document.querySelector(
        '[data-testid="highlight-menu"]',
      ) as HTMLElement | null;
      if (el) {
        const box = el.getBoundingClientRect();
        window.__menuFrames!.push({
          left: el.style.left,
          l: box.left,
          r: box.right,
        });
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });

  const cdp = await context.newCDPSession(page);
  const yLine = (await pointOnWord(page, "whispering", 1))!.y;
  const vw = await page.evaluate(() => window.innerWidth);
  let shown = false;
  for (let x = vw - 56; x > vw - 120 && !shown; x -= 12) {
    await touchTap(cdp, { x, y: yLine }, 500);
    await page.waitForTimeout(400);
    shown = await page.getByTestId("highlight-menu").isVisible();
  }
  expect(shown).toBe(true);
  await page.waitForTimeout(600);

  const frames = await page.evaluate(() => window.__menuFrames!);
  expect(frames.length).toBeGreaterThan(0);
  expect(new Set(frames.map((f) => f.left)).size).toBe(1);
  for (const f of frames) {
    expect(f.l).toBeGreaterThanOrEqual(0);
    expect(f.r).toBeLessThanOrEqual(vw);
  }
});

test("a later tap elsewhere dismisses the menu", async ({ page, context }) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  const pt = await pointOnWord(page, "whispering", 1);
  expect(pt).toBeTruthy();

  await armMenuWatcher(page);
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, pt!, 900);
  await page.waitForTimeout(1200);
  await expect(page.getByTestId("highlight-menu")).toBeVisible();

  const belowMenu = await page.evaluate(() => {
    const menu = document.querySelector('[data-testid="highlight-menu"]')!;
    return {
      x: window.innerWidth / 2,
      y: menu.getBoundingClientRect().bottom + 50,
    };
  });
  await touchTap(cdp, belowMenu, 60);

  await page.waitForTimeout(800);
  expect(await menuTimeline(page)).toEqual([
    expect.stringMatching(/SHOW$/),
    expect.stringMatching(/HIDE$/),
  ]);
  await expect(page.getByTestId("highlight-menu")).toBeHidden();
  // Dismissing is not a chrome toggle.
  await expect(page.getByTestId("ng-chrome")).toBeVisible();
});

test("selection tiles stay glyph-anchored when book CSS styles bare divs", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  await page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const style = doc.createElement("style");
    style.textContent = "body > div { margin: 1em; } body div { margin: 4px; }";
    doc.head.appendChild(style);
  });
  await page.waitForTimeout(400);

  const pt = await pointOnWord(page, "librarian", 0);
  expect(pt).toBeTruthy();
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, pt!, 900);
  await page.waitForTimeout(500);

  const out = await page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const el = doc.getElementById("beepub-sel-overlay");
    if (!el || el.children.length === 0) return null;
    const tiles = [...el.children].map((c) => {
      const r = c.getBoundingClientRect();
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    });
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const idx = (node.textContent ?? "").indexOf("librarian");
      if (idx < 0) continue;
      const range = doc.createRange();
      range.setStart(node, idx);
      range.setEnd(node, idx + "librarian".length);
      const w = range.getBoundingClientRect();
      return {
        tiles,
        word: { left: w.left, top: w.top, right: w.right, bottom: w.bottom },
      };
    }
    return null;
  });
  expect(out).toBeTruthy();
  const covering = out!.tiles.find(
    (t) =>
      t.left <= out!.word.left + 1 &&
      t.right >= out!.word.right - 1 &&
      t.top <= out!.word.top + 1 &&
      t.bottom >= out!.word.bottom - 1,
  );
  expect(covering).toBeTruthy();
});
