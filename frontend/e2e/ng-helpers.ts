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
 * the reader at a known geometry, engine readouts through the debug handle
 * (the section iframe lives in a closed shadow root), and trusted touch
 * input over CDP (which includes the browser's own click synthesis).
 */

export const FIXTURES = path.join(
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
    __fades?: number[];
    __turns?: string[];
    __lift?: { ghostIndex: number | null } | null;
    __restoreLoad?: () => void;
    __releaseLoad?: () => void;
    __armLift?: () => void;
    __liveLoads?: number;
    __stuckGhost?: unknown;
  }
}

export interface Fixture {
  file: string;
  /** Substring of the display title the library search matches on. */
  title: string;
  /** Text the first rendered section must contain before a test starts. */
  readyText: string;
  /** Upload content type; EPUB unless the fixture says otherwise. */
  mimeType?: string;
}

export const TOUCH_BOOK: Fixture = {
  file: "e2e-touch-book.epub",
  title: "Flicker Repro Book",
  readyText: "starship librarian",
};

/** Two chapters of unique sentences (the heal tests need unambiguous
 *  quotes), padded past the server's 500-word image-book threshold so the
 *  chrome shows the highlights entry. */
export const ANCHOR_BOOK: Fixture = {
  file: "e2e-anchor-book.epub",
  title: "Anchor Drift Ledger",
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

/** One long vertical-rl chapter: many pages to page through. */
export const VERTICAL_LONG_BOOK: Fixture = {
  file: "e2e-vertical-long-book.epub",
  title: "直書均勻格線",
  readyText: "話說天下大勢分久必合",
};

/** Two chapters with a ~15:1 text-size ratio: the weight scale has a
 *  shape uniform section counting could not fake. */
export const CHAPTERS_BOOK: Fixture = {
  file: "e2e-vertical-chapters-book.epub",
  title: "直書跨章格線",
  readyText: "甲章首段",
};

/** Three vertical chapters, one per section, each TOC entry pointing at
 *  an empty <p id> that sits behind another empty <p> and ahead of the
 *  heading — the way a publisher's export anchors its chapters. */
export const CHAPTER_ANCHORS_BOOK: Fixture = {
  file: "e2e-chapter-anchors-book.epub",
  title: "守塔人的三則日誌",
  readyText: "潮汐之章第1段",
};

/** One vertical chapter with a tall illustration alone in its own
 *  paragraph between blank lines, mid-text — a light novel's plate. */
export const VERTICAL_PLATE_BOOK: Fixture = {
  file: "e2e-vertical-plate-book.epub",
  title: "風車郵差的插圖頁",
  readyText: "風車之章第1段",
};

/** A vertical-rl book (page progression rtl) with a horizontal-tb
 *  illustration plate between its two chapters — the shape that made
 *  page turns loop at every chapter start. */
export const VERTICAL_MIXED_BOOK: Fixture = {
  file: "e2e-vertical-mixed-book.epub",
  title: "直書夾橫幅插畫卷",
  readyText: "卷一其1",
};

/** The same book with no page-progression-direction declared: the
 *  direction has to be inferred from its vertical text. */
export const VERTICAL_MIXED_UNDECLARED_BOOK: Fixture = {
  file: "e2e-vertical-mixed-undeclared-book.epub",
  title: "未宣告直書插畫卷",
  readyText: "卷一其1",
};

/** A horizontal zh-TW novel, no page-progression-direction, whose
 *  publisher boilerplate sheet carries `body.vrtl { writing-mode:
 *  vertical-rl }` on a class the body never wears (a Taiwanese
 *  publisher's InDesign export). Reads left to right. */
export const RAINY_POST_OFFICE_BOOK: Fixture = {
  file: "e2e-rainy-post-office-book.epub",
  title: "雨季郵局",
  readyText: "雨季郵局首頁",
};

/** Built like the Japanese publishers' ebpaj template: the one linked
 *  stylesheet is a shell of @import rules, and the writing mode, fonts
 *  and classes live in the imported sheets (one of which imports again).
 *  Nothing renders right unless the whole @import chain is resolved. */
export const IMPORT_SHELL_BOOK: Fixture = {
  file: "e2e-import-shell-book.epub",
  title: "縱組範本試驗帖",
  readyText: "縱組範本首行",
};

/** Three long horizontal chapters (some sixty phone pages each) of
 *  numbered log entries: laying one out is real work, the way a novel's
 *  chapter is on a phone. */
export const LONG_CHAPTERS_BOOK: Fixture = {
  file: "e2e-long-chapters-book.epub",
  title: "Signal Station Daybooks",
  readyText: "Signal log northgate entry 0001",
};

/** Nine vertical chapters, one per section and TOC entry (the last a
 *  short 版權頁), some seventeen phone pages each; the fifth carries a
 *  small inline picture. Enough sections that opening the book does not
 *  fetch them all: the reader's prefetch reaches three ahead. */
export const NINE_CHAPTERS_BOOK: Fixture = {
  file: "e2e-nine-chapters-book.epub",
  title: "渡船九日誌",
  readyText: "啟航之章第1段",
};

/** Nested TOC with fragment entries, a same-file footnote, a cross-file
 *  note reference, a plain cross-file link, one unique search token
 *  ("quillstorm") and one frequent one ("lantern"). */
export const NOTES_BOOK: Fixture = {
  file: "e2e-notes-book.epub",
  title: "Margin Notes Almanac",
  readyText: "almanac opens with lanterns",
};

/** Four short chapters; chapters 2–4 each open on a plate (an <img>, an
 *  SVG <image>, an <img>) under OEBPS/images, referenced with `../` from
 *  OEBPS/text — the shape the image prefetch has to resolve. */
export const PLATES_BOOK: Fixture = {
  file: "e2e-plates-book.epub",
  title: "Copperplate Weather Journal",
  readyText: "frost ledger kept by a lighthouse cook",
};

/** A plain-text novel the way they come off the net: 《title》 and 作者
 *  header lines, a TOC listing up top, two parts (卷) of chapters (章)
 *  and a 番外, paragraphs indented with full-width spaces. Uploaded as
 *  TXT; the server converts it to an EPUB. */
/** Simplified Chinese; the converted title is what the seeded book carries. */
export const SIMPLIFIED_TXT_BOOK: Fixture = {
  file: "e2e-fog-harbour.txt",
  title: "霧港夜航",
  readyText: "沒有燈的船",
  mimeType: "text/plain",
};

/** Simplified Chinese, uploaded unconverted for the detail-page action. */
export const SIMPLIFIED_TXT_BOOK_2: Fixture = {
  file: "e2e-lighthouse-keeper.txt",
  title: "灯塔守夜人",
  readyText: "守夜人",
  mimeType: "text/plain",
};

/** Calibre-made AZW3 (KF8): unpacks to an EPUB whose first spine item
 *  is a non-linear cover page; chapter two carries an inline image. */
export const AZW3_BOOK: Fixture = {
  file: "e2e-windmill-postman.azw3",
  title: "風車島郵差",
  readyText: "風車島上只有一個郵差",
  mimeType: "application/vnd.amazon.ebook",
};

/** Old MOBI7: one HTML file, split on its page breaks at ingest. */
export const MOBI7_BOOK: Fixture = {
  file: "e2e-ferry-last-boat.mobi",
  title: "渡口的最後一班船",
  readyText: "船夫從不等人",
  mimeType: "application/x-mobipocket-ebook",
};

export const TXT_BOOK: Fixture = {
  file: "e2e-tide-clocktower.txt",
  title: "潮汐鐘樓手記",
  readyText: "退潮之後",
  mimeType: "text/plain",
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
  // Search by title rather than scan a page: the library outgrows any
  // page size. Oldest first — the digest lookup that links a downloaded
  // copy picks the earliest book with that file, so seed that one.
  const params = new URLSearchParams({
    library: library.id,
    search: fixture.title,
    sort: "created_at",
    order: "asc",
    limit: "200",
  });
  const books = await (await request.get(`/api/books?${params}`)).json();
  const existing = books.items?.find((b: Record<string, string>) =>
    (b.display_title ?? b.epub_title ?? "").includes(fixture.title),
  );
  if (existing) return existing.id;
  const uploaded = await request.post("/api/books", {
    multipart: {
      file: {
        name: fixture.file,
        mimeType: fixture.mimeType ?? "application/epub+zip",
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

/** What the browser says of its connection (`navigator.connection`),
 *  from the first script on. `{ saveData: true }` is how a spec keeps the
 *  reader from bringing in the rest of a streamed book's text behind the
 *  page: the specs about chapters that are not in memory need them to
 *  stay out. */
export function connection(
  page: Page,
  value: { saveData?: boolean; type?: string },
) {
  return page.addInitScript((value) => {
    Object.defineProperty(Navigator.prototype, "connection", {
      configurable: true,
      get: () => value,
    });
  }, value);
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

/** The one-time gesture coach mark (shared key with the current reader)
 *  would sit over the page and eat the first tap of every fresh context. */
export function seedGesturesSeen(page: Page) {
  return page.addInitScript(() => {
    try {
      localStorage.setItem("reader-gestures-seen", "1");
    } catch {
      // storage unavailable — the hint shows, which only matters on device
    }
  });
}

/** Open the reader at a fixed geometry and wait for the first section.
 *  `overrides` are query params, plus `restore: "1"` to keep the reader's
 *  own restored position instead of resetting to the first page.
 *
 *  Page turns are bare jumps (`turn=instant`, a mode only the query
 *  reaches) so a spec can read the page right after turning it; pass
 *  `turn: "fade"` / `"slide"` for the reader's own modes, or `turn: ""`
 *  to leave the choice to what is stored. */
export async function openBook(
  page: Page,
  bookId: string,
  overrides: Record<string, string> = {},
  fixture: Fixture = TOUCH_BOOK,
) {
  const { restore, ...query } = overrides;
  // Session-only overrides of the reader settings (px gutters: mx is
  // left/right, my top/bottom).
  const params = new URLSearchParams({
    size: "18",
    lh: "1.8",
    mx: "24",
    my: "48",
    turn: "instant",
    ...query,
  });
  if (!params.get("turn")) params.delete("turn");
  await seedGesturesSeen(page);
  await page.goto(`/books/${bookId}/read?${params}`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  // The reader restores saved progress (possibly another section, left by
  // an earlier test); the specs assume the first section's first page
  // unless they asked for a target themselves.
  if (!query.cfi && !restore) {
    // First linear section: a converted Kindle book opens on a
    // non-linear cover page at index 0.
    const first = await page.evaluate(() => {
      const core = window.__beepubReaderNG.core;
      const index = core.firstLinearIndex();
      core.goTo(index);
      return index;
    });
    await expect
      .poll(() =>
        page.evaluate((index) => {
          const l = window.__beepubReaderNG.core.lastLocation;
          return l.index === index && l.fraction === 0;
        }, first),
      )
      .toBe(true);
  }
  await expect
    .poll(() =>
      page.evaluate((text) => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        return doc.body?.textContent?.includes(text) ?? false;
      }, fixture.readyText),
    )
    .toBe(true);
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

/** Two chapters of prose; chapter two carries print page markers the way
 *  publisher files do: an empty inline anchor (`<a id="page_43"/>`) inside
 *  a paragraph and an empty pagebreak span between paragraphs. */
export const PAGE_MARKERS_BOOK: Fixture = {
  file: "e2e-page-markers-book.epub",
  title: "Page Marker Gazette",
  readyText: "harbor office",
};

/** A six-page right-to-left comic (page four is a two-page spread), packed
 *  into a pre-paginated EPUB at ingest. An image book: no readyText. */
export const CBZ_BOOK: Fixture = {
  file: "e2e-violin-platform.cbz",
  title: "月台小提琴手",
  readyText: "",
  mimeType: "application/vnd.comicbook+zip",
};

/** Open an image book in the reader: BookReader parses it, finds the layout
 *  pre-paginated and hands it to the image pager. Resolves once the pager
 *  shows its restored page with every image on screen decoded. */
export async function openComic(page: Page, bookId: string) {
  await seedGesturesSeen(page);
  await page.goto(`/books/${bookId}/read`);
  await page.waitForFunction(() => !!window.__beepubReaderNG?.pager, null, {
    timeout: 30_000,
  });
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.pager.loaded))
    .toBe(true);
}

/** The pager's position as the debug handle reports it. */
export function pagerState(page: Page) {
  return page.evaluate(() => {
    const p = window.__beepubReaderNG.pager;
    return {
      page: p.page as number,
      total: p.total as number,
      shown: p.shown as number[],
      twoPage: p.twoPage as boolean,
      shift: p.shift as boolean,
      padding: p.padding as number,
      mode: p.mode as string,
      flow: p.flow as string,
      rtl: p.rtl as boolean,
      scale: p.scale as number,
      cfi: p.cfi as string,
    };
  });
}

/** Pick an image-pager setting through the settings sheet. */
export async function setPagerSetting(
  page: Page,
  row: "setting-pager-mode" | "setting-pager-direction" | "setting-pager-shift",
  label: string,
) {
  await page.getByRole("button", { name: "Reader settings" }).click();
  await page.getByTestId(row).getByRole("button", { name: label }).click();
  await page.keyboard.press("Escape");
}

/** Press a stepper row's + or − in the settings sheet `times` times. */
export async function stepPagerSetting(
  page: Page,
  setting: "Page padding",
  dir: "up" | "down",
  times = 1,
) {
  await page.getByRole("button", { name: "Reader settings" }).click();
  const name = `${dir === "up" ? "Increase" : "Decrease"} ${setting}`;
  for (let i = 0; i < times; i++)
    await page.getByRole("button", { name }).click();
  await page.keyboard.press("Escape");
}

/** Run the web build as the iOS app: Capacitor reads
 *  `CapacitorCustomPlatform` first, and plugins without a native bridge
 *  fall back to their web implementations (Preferences → localStorage,
 *  Filesystem → IndexedDB). `settings` are seeded into localStorage. */
export function simulateApp(page: Page, settings: Record<string, string>) {
  return page.addInitScript((settings) => {
    (
      window as unknown as { CapacitorCustomPlatform: { name: string } }
    ).CapacitorCustomPlatform = { name: "ios" };
    for (const [k, v] of Object.entries(settings)) localStorage.setItem(k, v);
    // The stack is plain http, so the page is not a secure context and
    // lacks crypto.randomUUID (imports and highlights mint ids with it).
    // The app itself always runs in one (capacitor:// / https).
    if (typeof crypto.randomUUID !== "function") {
      crypto.randomUUID = () => {
        const b = crypto.getRandomValues(new Uint8Array(16));
        b[6] = (b[6] & 0x0f) | 0x40;
        b[8] = (b[8] & 0x3f) | 0x80;
        const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join(
          "",
        );
        return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}` as ReturnType<
          typeof crypto.randomUUID
        >;
      };
    }
  }, settings);
}
