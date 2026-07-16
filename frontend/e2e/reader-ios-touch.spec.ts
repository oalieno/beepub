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

  // Quick-tap mid-page. The window's width, not the iframe's: in
  // paginated mode the iframe spans every column of the chapter, so its
  // horizontal center sits far off-screen. Vertically the iframe rect is
  // real — 60% down is below the selection and the menu anchored above
  // it, and clear of the parent document's bottom bar. A quick tap never
  // selects, so it lands on the ontapdismiss path.
  const midPage = await page.evaluate(() => {
    const io = (
      document.querySelector("iframe") as HTMLIFrameElement
    ).getBoundingClientRect();
    return { x: window.innerWidth / 2, y: io.top + io.height * 0.6 };
  });
  await touchTap(cdp, midPage, 60);

  await page.waitForTimeout(800);
  expect(await menuTimeline(page)).toEqual([
    expect.stringMatching(/SHOW$/),
    expect.stringMatching(/HIDE$/),
  ]);
  await expect(page.getByTestId("highlight-menu")).toBeHidden();
});
