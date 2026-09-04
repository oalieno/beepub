import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  expect,
  devices,
  type APIRequestContext,
  type CDPSession,
  type Page,
} from "@playwright/test";
import { LIBRARY_NAME } from "./helpers";

/**
 * Shared plumbing for the reader-ng specs: fixture seeding, opening
 * read-ng at a known geometry, engine readouts through the debug handle
 * (the section iframe lives in a closed shadow root), and trusted touch
 * input over CDP (which includes the browser's own click synthesis).
 */

const FIXTURES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
);

/** iPhone 13 descriptor minus the browser it names: the reader's iOS
 *  paths are UA-gated, and the suite runs on chromium. */
export const { defaultBrowserType: _webkit, ...iphone } = devices["iPhone 13"];

declare global {
  interface Window {
    __beepubReaderNG?: any;
    __menuLog?: string[];
    __menuT0?: number;
    __menuFrames?: { left: string; l: number; r: number }[];
  }
}

export interface Fixture {
  file: string;
  /** Substring of the display title the library search matches on. */
  title: string;
  /** Text the first rendered section must contain before a test starts. */
  readyText: string;
}

export const TOUCH_BOOK: Fixture = {
  file: "e2e-touch-book.epub",
  title: "Flicker Repro Book",
  readyText: "starship librarian",
};

export const ANCHOR_BOOK: Fixture = {
  file: "e2e-anchor-book.epub",
  title: "Anchor Drift Book",
  readyText: "lighthouse keeper",
};

export const VERTICAL_BOOK: Fixture = {
  file: "e2e-vertical-book.epub",
  title: "縱書測試之卷",
  readyText: "話說天下大勢",
};

export const VPUNCT_BOOK: Fixture = {
  file: "e2e-vpunct-book.epub",
  title: "E2E 直排標點測試",
  readyText: "免費服務已終止",
};

/** Two chapters with a ~15:1 text-size ratio: the weight scale has a
 *  shape uniform section counting could not fake. */
export const CHAPTERS_BOOK: Fixture = {
  file: "e2e-vertical-chapters-book.epub",
  title: "直書跨章格線",
  readyText: "甲章首段",
};

/** Upload the fixture into the E2E library once; return its book id.
 *  Seeding by title keeps re-runs from piling copies into the persistent
 *  e2e database (which skews the search ranking other specs rely on). */
export async function seedFixture(
  request: APIRequestContext,
  fixture: Fixture,
): Promise<string> {
  const libraries = await (await request.get("/api/libraries")).json();
  const library = libraries.find(
    (l: { name: string }) => l.name === LIBRARY_NAME,
  );
  expect(library).toBeTruthy();
  const books = await (
    await request.get(`/api/libraries/${library.id}/books?limit=100`)
  ).json();
  const existing = books.items?.find((b: Record<string, string>) =>
    (b.display_title ?? b.epub_title ?? "").includes(fixture.title),
  );
  if (existing) return existing.id;
  const uploaded = await request.post("/api/books", {
    multipart: {
      file: {
        name: fixture.file,
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(path.join(FIXTURES, fixture.file)),
      },
      library_id: library.id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  return (await uploaded.json()).id;
}

export function seedBook(request: APIRequestContext) {
  return seedFixture(request, TOUCH_BOOK);
}

/** Put a book's saved position back on its first page (progress rows
 *  persist across runs; the reader restores them). */
export async function resetProgress(
  request: APIRequestContext,
  bookId: string,
  cfi = "epubcfi(/6/2!/4/2/1:0)",
) {
  const res = await request.put(`/api/books/${bookId}/progress`, {
    data: { cfi, percentage: 0, section_index: 0, section_page: 1 },
  });
  expect(res.ok()).toBeTruthy();
}

/** Open read-ng at a fixed geometry and wait for the first section.
 *  `overrides` are query params, plus `restore: "1"` to keep the reader's
 *  own restored position instead of resetting to the first page. */
export async function openBook(
  page: Page,
  bookId: string,
  overrides: Record<string, string> = {},
  fixture: Fixture = TOUCH_BOOK,
) {
  const { restore, ...query } = overrides;
  // panel=0: the geometry instrument would sit over the lower right.
  const params = new URLSearchParams({
    size: "18",
    lh: "1.8",
    gap: "7",
    margin: "48",
    cols: "1",
    panel: "0",
    ...query,
  });
  await page.goto(`/books/${bookId}/read-ng?${params}`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await expect
    .poll(() =>
      page.evaluate((text) => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        return doc.body?.textContent?.includes(text) ?? false;
      }, fixture.readyText),
    )
    .toBe(true);
  // The reader restores saved progress; the specs assume the section's
  // first page unless they asked for a target themselves.
  if (!query.cfi && !restore) {
    await page.evaluate(() => window.__beepubReaderNG.core.goTo(0));
    await expect
      .poll(() =>
        page.evaluate(() => {
          const l = window.__beepubReaderNG.core.lastLocation;
          return l.index === 0 && l.fraction === 0;
        }),
      )
      .toBe(true);
  }
  await page.waitForTimeout(500);
}

export function location(page: Page) {
  return page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return {
      index: l.index as number,
      fraction: l.fraction as number,
      reason: l.reason as string,
    };
  });
}

/** Record every show/hide of the highlight menu with a timestamp. */
export async function armMenuWatcher(page: Page) {
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

export function menuTimeline(page: Page): Promise<string[]> {
  return page.evaluate(() => window.__menuLog ?? []);
}

export async function touchTap(
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

export async function swipe(
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
export async function pointOnWord(
  page: Page,
  word: string,
  occurrence: number,
) {
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

/** The iOS selection overlay's group opacity and tile fill. */
export function overlayState(page: Page) {
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

/** Drawn marks on the current section's overlayer (iframe coordinates):
 *  one entry per saved highlight, with its fill and rects. */
export function marks(page: Page) {
  return page.evaluate(() => {
    const overlayer = window.__beepubReaderNG.core.getContents()[0].overlayer;
    const svg: SVGSVGElement | undefined = overlayer?.element;
    if (!svg) return [];
    return Array.from(svg.querySelectorAll("g")).map((g) => ({
      fill: g.getAttribute("fill"),
      rects: Array.from(g.querySelectorAll("rect")).map((r) => ({
        x: Number(r.getAttribute("x")),
        y: Number(r.getAttribute("y")),
        w: Number(r.getAttribute("width")),
        h: Number(r.getAttribute("height")),
      })),
    }));
  });
}
