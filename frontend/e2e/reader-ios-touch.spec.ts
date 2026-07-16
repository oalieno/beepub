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
 * Regression tests for the iOS highlight-menu flicker pair (b27e913,
 * d09d440): on touch devices a single gesture arrives as several events
 * (touchstart → touchend → a synthesized click, marks even emit twice),
 * and the menu used to blink open → closed → open, or vanish outright
 * after a long hold.
 *
 * The chromium project emulates an iPhone here: the reader's iOS touch
 * path is gated on the user agent, and CDP — chromium-only — dispatches
 * trusted touch input including the browser's own click synthesis, which
 * is exactly the residue these bugs were about.
 */

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-touch-book.epub",
);

// The fixture's internal dc:title. Its chapter repeats one long paragraph
// so long-presses land on plain prose regardless of pagination.
const BOOK_TITLE = "Flicker Repro Book";
// "librarian" in the first paragraph.
const HIGHLIGHT_CFI = "epubcfi(/6/2!/4/4,/1:13,/1:22)";

const { defaultBrowserType: _webkit, ...iphone } = devices["iPhone 13"];
test.use({ storageState: ADMIN_STATE, ...iphone });

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

async function openBook(page: Page, bookId: string) {
  // The first-open gesture coach mark would swallow the first tap.
  await page.addInitScript(() =>
    localStorage.setItem("reader-gestures-seen", "1"),
  );
  await page.goto(`/books/${bookId}/read`);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.getByText("starship librarian").first()).toBeVisible({
    timeout: 30_000,
  });
  // Location generation and progress restore can rerender the section
  // shortly after first paint; let the reader settle before touching.
  await page.waitForTimeout(2500);
}

/**
 * Record every appearance/disappearance of the highlight menu with a
 * timestamp. A MutationObserver (not polling) so even a brief blink of
 * the pre-fix kind is caught.
 */
async function armMenuWatcher(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __menuLog: string[]; __menuT0: number };
    w.__menuLog = [];
    w.__menuT0 = performance.now();
    let visible = !!document.querySelector('[data-testid="highlight-menu"]');
    new MutationObserver(() => {
      const v = !!document.querySelector('[data-testid="highlight-menu"]');
      if (v === visible) return;
      visible = v;
      w.__menuLog.push(
        `${Math.round(performance.now() - w.__menuT0)}ms ${v ? "SHOW" : "HIDE"}`,
      );
    }).observe(document.body, { childList: true, subtree: true });
  });
}

function menuTimeline(page: Page): Promise<string[]> {
  return page.evaluate(
    () => (window as unknown as { __menuLog: string[] }).__menuLog,
  );
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

/** Viewport point of a word inside the epub iframe (nth occurrence). */
async function pointOnWord(page: Page, word: string, occurrence: number) {
  return page.evaluate(
    ([word, occurrence]) => {
      const ifr = document.querySelector("iframe") as HTMLIFrameElement;
      const doc = ifr.contentDocument!;
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
        const io = ifr.getBoundingClientRect();
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

test("long-press selection survives the synthesized click that follows", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  // Second paragraph — clear of the highlight the tap test seeds.
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

  // The drawn selection must carry the reader theme's tint (light theme
  // default; the pre-fix hardcode was blue) as solid rects under one
  // group opacity, so overlapping client rects don't stack darker.
  const overlay = await page.evaluate(() => {
    const doc = (document.querySelector("iframe") as HTMLIFrameElement)
      .contentDocument!;
    const el = doc.getElementById("beepub-sel-overlay");
    const child = el?.firstElementChild;
    if (!el || !child) return null;
    return {
      opacity: getComputedStyle(el).opacity,
      fill: getComputedStyle(child).backgroundColor,
    };
  });
  expect(overlay).toEqual({ opacity: "0.3", fill: "rgb(196, 146, 74)" });
});

test("tapping an existing highlight opens the menu once, without a blink", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  const highlights = await (
    await page.request.get(`/api/books/${bookId}/highlights`)
  ).json();
  if (
    !highlights.some(
      (h: { cfi_range: string }) => h.cfi_range === HIGHLIGHT_CFI,
    )
  ) {
    const created = await page.request.post(
      `/api/books/${bookId}/highlights`,
      { data: { cfi_range: HIGHLIGHT_CFI, text: "librarian", color: "yellow" } },
    );
    expect(created.ok()).toBeTruthy();
  }

  await openBook(page, bookId);

  // The mark pane lives in the parent document, overlaying the iframe.
  const pt = await page.evaluate(() => {
    const el = document.querySelector('[ref="hl"]');
    if (!el) return null;
    const rect = (el.querySelector("rect,path") ?? el).getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  });
  expect(pt).toBeTruthy();

  await armMenuWatcher(page);
  const cdp = await context.newCDPSession(page);
  // A quick tap arrives as touchstart + touchend + the browser's own
  // synthesized click; the mark emits markClicked for the first and last,
  // with the touchend's tap-dismiss squeezed in between (the pre-fix
  // blink).
  await touchTap(cdp, pt!, 80);

  await page.waitForTimeout(1200);
  expect(await menuTimeline(page)).toEqual([expect.stringMatching(/SHOW$/)]);
  await expect(page.getByTestId("highlight-menu")).toBeVisible();
});

test("drag selection paints line fragments, not paragraph slabs", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  // Drag from the chapter heading into the middle of the second
  // paragraph, so the whole first paragraph ends up inside the range.
  // getClientRects() would then include that paragraph's border box — a
  // slab as tall as the paragraph — which native selection painting
  // never shows; the overlay must stick to per-line fragments.
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
    const doc = (document.querySelector("iframe") as HTMLIFrameElement)
      .contentDocument!;
    const el = doc.getElementById("beepub-sel-overlay");
    if (!el) return null;
    const p = doc.querySelector("p")!.getBoundingClientRect();
    return {
      rects: [...el.children].map((c) => {
        const r = c.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, height: r.height };
      }),
      paragraph: { top: p.top, bottom: p.bottom, height: p.height },
    };
  });
  expect(overlay).toBeTruthy();
  // Several lines' worth of fragments (an empty overlay must not pass) …
  expect(overlay!.rects.length).toBeGreaterThan(3);
  // … and none of them anywhere near paragraph-sized.
  for (const r of overlay!.rects) {
    expect(r.height).toBeLessThan(overlay!.paragraph.height / 2);
  }
  // Within the fully-covered paragraph the fragments must tile the way
  // native selection paints — full line boxes, no gap line-to-line
  // (highlight marks hug the glyphs instead; the contrast is deliberate).
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
});

test("menu opened near the screen edge is clamped from the first frame", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  // Sample the menu every animation frame — rAF runs just before paint,
  // so the first sample is the first position actually shown. The menu
  // used to paint one frame at the unclamped (overflowing) spot before a
  // second markClicked corrected it — and stayed there forever on paths
  // that only fire once.
  await page.evaluate(() => {
    const w = window as unknown as {
      __menuFrames: { left: string; l: number; r: number }[];
    };
    w.__menuFrames = [];
    const sample = () => {
      const el = document.querySelector(
        '[data-testid="highlight-menu"]',
      ) as HTMLElement | null;
      if (el) {
        const box = el.getBoundingClientRect();
        w.__menuFrames.push({ left: el.style.left, l: box.left, r: box.right });
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });

  const cdp = await context.newCDPSession(page);
  const yLine = (await pointOnWord(page, "whispering", 1))!.y;
  const vw = await page.evaluate(() => window.innerWidth);
  // Long-press close to the right edge, so the centered menu would
  // overflow unclamped. Step left when the press lands on whitespace
  // (which selects nothing), staying clear of the parent document's
  // 48px tap-nav strip that swallows touches.
  let shown = false;
  for (let x = vw - 56; x > vw - 120 && !shown; x -= 12) {
    await touchTap(cdp, { x, y: yLine }, 500);
    await page.waitForTimeout(400);
    shown = await page.getByTestId("highlight-menu").isVisible();
  }
  expect(shown).toBe(true);
  await page.waitForTimeout(600);

  const frames = await page.evaluate(
    () =>
      (window as unknown as { __menuFrames: { left: string; l: number; r: number }[] })
        .__menuFrames,
  );
  expect(frames.length).toBeGreaterThan(0);
  // Painted at a single position — no overflow-then-jump …
  expect(new Set(frames.map((f) => f.left)).size).toBe(1);
  // … and that position is fully on-screen.
  for (const f of frames) {
    expect(f.l).toBeGreaterThanOrEqual(0);
    expect(f.r).toBeLessThanOrEqual(vw);
  }
});

test("changing the page margin realigns highlights and resizes tap zones", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  const highlights = await (
    await page.request.get(`/api/books/${bookId}/highlights`)
  ).json();
  if (
    !highlights.some(
      (h: { cfi_range: string }) => h.cfi_range === HIGHLIGHT_CFI,
    )
  ) {
    const created = await page.request.post(
      `/api/books/${bookId}/highlights`,
      { data: { cfi_range: HIGHLIGHT_CFI, text: "librarian", color: "yellow" } },
    );
    expect(created.ok()).toBeTruthy();
  }
  await openBook(page, bookId);

  // Offset between the drawn highlight mark and the live position of its
  // word. Margins used to be theme CSS: changing them reflowed the text
  // without resizing the content, so the annotation pane never
  // re-measured its ranges and the marks drifted off the words.
  const alignment = () =>
    page.evaluate(() => {
      const ifr = document.querySelector("iframe") as HTMLIFrameElement;
      const doc = ifr.contentDocument!;
      const mark =
        document.querySelector('[ref="hl"]') ?? doc.querySelector('[ref="hl"]');
      if (!mark) return null;
      const markRect = (
        mark.querySelector("rect,path") ?? mark
      ).getBoundingClientRect();
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const n = walker.currentNode;
        const idx = (n.textContent ?? "").indexOf("librarian");
        if (idx < 0) continue;
        const r = doc.createRange();
        r.setStart(n, idx);
        r.setEnd(n, idx + 9);
        const wr = r.getBoundingClientRect();
        const io = ifr.getBoundingClientRect();
        return {
          dx: markRect.left - (io.left + wr.left),
          dy: markRect.top - (io.top + wr.top),
          pad: doc.body.style.getPropertyValue("padding-left"),
        };
      }
      return null;
    });

  const before = await alignment();
  expect(before).toBeTruthy();
  expect(Math.abs(before!.dx)).toBeLessThan(1.5);
  expect(Math.abs(before!.dy)).toBeLessThan(1.5);
  expect(before!.pad).toBe("32px");

  // Change the margin through the real settings UI (tap to reveal the
  // bottom bar first).
  await page.mouse.click(195, 500);
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Narrow", exact: true }).click();
  await page.waitForTimeout(1500);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(800);

  const after = await alignment();
  expect(after).toBeTruthy();
  expect(Math.abs(after!.dx)).toBeLessThan(1.5);
  expect(Math.abs(after!.dy)).toBeLessThan(1.5);
  expect(after!.pad).toBe("16px");

  // Tap-to-turn zones must shrink with the margin, or they'd cover the
  // first and last line of every page.
  const zone = await page
    .getByRole("button", { name: "Previous page" })
    .boundingBox();
  expect(zone?.width).toBe(16);
});

// Not a regression test of a past bug but the watcher's proof of life:
// dismissal produces the HIDE transition the two tests above assert never
// happens, so a broken watcher can't make them pass vacuously. It also
// pins the flip side of the just-shown grace — a deliberate tap after it
// expires must still close the menu.
test("a later tap elsewhere dismisses the menu", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);

  const pt = await pointOnWord(page, "whispering", 1);
  expect(pt).toBeTruthy();

  await armMenuWatcher(page);
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, pt!, 900);
  await page.waitForTimeout(1200);
  await expect(page.getByTestId("highlight-menu")).toBeVisible();

  // Quick-tap safely below the menu, derived from its actual rect (a
  // fixed page point is brittle: the clamp is allowed to move the menu
  // and once shifted it right over the hardcoded spot, swallowing the
  // tap). The window's width for x, not the iframe's — in paginated mode
  // the iframe spans every column of the chapter, so its horizontal
  // center sits far off-screen. A quick tap never selects, so it lands
  // on the ontapdismiss path.
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
});
