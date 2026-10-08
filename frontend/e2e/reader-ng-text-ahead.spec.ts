import {
  test,
  expect,
  type BrowserContext,
  type Page,
  type Route,
} from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  NINE_CHAPTERS_BOOK,
  connection,
  iphone,
  openBook,
  resetProgress,
  seedFixture,
  touchTap,
} from "./ng-helpers";

/**
 * reader-ng: the rest of a streamed book's text, brought in behind the
 * page.
 *
 * The prefetch keeps a few sections around the reader. Behind it, slowly,
 * the documents of the sections further on are fetched too — text only,
 * into memory, for this session — so that a reader who loses the
 * connection in the middle of the book can read on. What is under test:
 * it is one request at a time, in reading order; a request of its own
 * that is slow holds up nothing the reader asks for, and is not made
 * again when the reader moves; it rests on some three megabytes of text
 * ahead of the reader and sets off again when reading has used most of
 * that up; a browser that asks for data to be saved gets none of it (a
 * cellular connection that does not ask is fetched over all the same); a
 * request that fails is the last until the connection is back; a hidden document fetches nothing; and
 * nothing is left running when the reader is closed.
 *
 * Every test routes the book's content requests, which keeps the
 * browser's HTTP cache out of it. `core.crawl` is the debug handle that
 * says where the fetch stands.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });
test.setTimeout(90_000);

const CONTENT = "**/api/books/*/content/**";
const MB = 1024 * 1024;

interface Wire {
  /** `start c-005`, `end c-005`, … for the chapters' documents, in the
   *  order the browser saw them. */
  log: string[];
  /** The requests made for pictures. */
  pictures: string[];
  /** Hold requests for the chapter until the returned function is
   *  called. */
  hold(chapter: string): () => void;
  /** Answer the chapter with `bytes` more of markup that says nothing. */
  pad(chapter: string, bytes: number): void;
}

async function wire(page: Page): Promise<Wire> {
  const log: string[] = [];
  const held = new Map<string, Promise<void>>();
  const padded = new Map<string, number>();
  const chapter = (url: string) => /(c-\d{3})\.xhtml/.exec(url)?.[1] ?? null;
  const pictures: string[] = [];
  page.on("request", (r) => {
    const c = chapter(r.url());
    if (c) log.push(`start ${c}`);
    if (/\/content\/.*\.png$/.test(r.url())) pictures.push(r.url());
  });
  for (const over of ["requestfinished", "requestfailed"] as const)
    page.on(over, (r) => {
      const c = chapter(r.url());
      if (c) log.push(`end ${c}`);
    });
  await page.route(CONTENT, async (route: Route) => {
    const c = chapter(route.request().url());
    if (c) await held.get(c);
    const bytes = c ? padded.get(c) : undefined;
    if (!bytes) return route.continue().catch(() => {});
    try {
      const response = await route.fetch();
      const body = (await response.text()).replace(
        "</body>",
        `<!-- ${"pad ".repeat(bytes / 4)}--></body>`,
      );
      await route.fulfill({ response, body });
    } catch {
      // the page went away, or the context went offline, meanwhile
    }
  });
  return {
    log,
    pictures,
    hold(c) {
      let release: () => void = () => {};
      held.set(c, new Promise((resolve) => (release = resolve)));
      return () => {
        held.delete(c);
        release();
      };
    },
    pad: (c, bytes) => void padded.set(c, bytes),
  };
}

const starts = (w: Wire, c: string) =>
  w.log.filter((line) => line === `start ${c}`).length;

async function open(page: Page) {
  const bookId = await seedFixture(page.request, NINE_CHAPTERS_BOOK);
  await resetProgress(page.request, bookId);
  await openBook(page, bookId, {}, NINE_CHAPTERS_BOOK);
  return bookId;
}

function available(page: Page, index: number): Promise<boolean> {
  return page.evaluate(
    (index) => window.__beepubReaderNG.core.sectionAvailable(index),
    index,
  );
}

function crawl(
  page: Page,
): Promise<{ state: string; ahead: number; fetching: string | null }> {
  return page.evaluate(() => window.__beepubReaderNG.core.crawl);
}

const crawlState = (page: Page) => crawl(page).then((c) => c.state);
/** The chapter the crawl is out for. */
const fetching = (page: Page) =>
  crawl(page).then((c) => /(c-\d{3})\.xhtml/.exec(c.fetching ?? "")?.[1]);

/** Jump, and wait until the reader is there. */
async function goTo(page: Page, index: number) {
  await page.evaluate(
    (index) => window.__beepubReaderNG.core.goTo(index),
    index,
  );
  await expect
    .poll(() =>
      page.evaluate(() => window.__beepubReaderNG.core.lastLocation.index),
    )
    .toBe(index);
}

function pageText(page: Page): Promise<string> {
  return page.evaluate(
    () =>
      (window.__beepubReaderNG.core.getContents()[0].doc as Document).body
        .textContent ?? "",
  );
}

const tocDialog = (page: Page) =>
  page.getByRole("dialog", { name: "Table of Contents" });

async function showBar(page: Page, context: BrowserContext) {
  const bar = page.getByRole("toolbar", { name: "Reading controls" });
  if (!(await bar.isVisible())) {
    const cdp = await context.newCDPSession(page);
    await touchTap(cdp, { x: 195, y: 420 }, 60);
  }
  await expect(bar).toBeVisible();
  return bar;
}

test("the rest of the book's text comes in behind the page, one request at a time and in order; offline, a far chapter picked from the table of contents opens", async ({
  page,
  context,
}) => {
  const w = await wire(page);
  await open(page);
  // The prefetch reaches three sections ahead of the first page; the
  // rest is the crawl's.
  await expect.poll(() => available(page, 8)).toBe(true);
  await expect.poll(() => crawlState(page)).toBe("done");
  const beyond = ["c-005", "c-006", "c-007", "c-008", "c-009"];
  for (const c of beyond) expect(starts(w, c)).toBe(1);
  // Each was asked for only when the one before it had been answered.
  const order = w.log.filter((line) => beyond.includes(line.slice(-5)));
  expect(order).toEqual(beyond.flatMap((c) => [`start ${c}`, `end ${c}`]));
  // Text only: the fifth chapter's picture was not fetched with it.
  expect(w.pictures).toEqual([]);

  await context.setOffline(true);
  const bar = await showBar(page, context);
  await bar.getByRole("button", { name: "Table of Contents" }).click();
  const dialog = tocDialog(page);
  await expect(dialog).toBeVisible();
  // Nothing is marked as out of reach.
  await expect(dialog.locator("[data-toc-unavailable]")).toHaveCount(0);
  await dialog.getByRole("button", { name: "歸港", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => pageText(page)).toContain("歸港之章第1段");
  expect(
    await page.evaluate(() => window.__beepubReaderNG.core.lastLocation.index),
  ).toBe(7);
  // From memory: it was not asked for again.
  expect(starts(w, "c-008")).toBe(1);
  await context.setOffline(false);
});

test("a slow request of the crawl's holds up nothing the reader asks for, no second one is made beside it, and it is not made again when the reader moves", async ({
  page,
}) => {
  const w = await wire(page);
  const release = w.hold("c-005");
  await open(page);
  await expect.poll(() => fetching(page)).toBe("c-005");

  // A jump to a chapter that is not in memory: its own request goes out
  // and is answered while the crawl's is still out.
  await goTo(page, 7);
  await expect.poll(() => pageText(page)).toContain("歸港之章第1段");
  expect(await fetching(page)).toBe("c-005");
  expect(w.log).toContain("end c-008");
  expect(w.log).not.toContain("end c-005");
  // The crawl has gone no further meanwhile.
  expect(starts(w, "c-006")).toBe(0);

  // Back to where the crawl set off from; what it was out for comes, and
  // it goes on from there.
  await goTo(page, 0);
  expect(await fetching(page)).toBe("c-005");
  release();
  await expect.poll(() => available(page, 5)).toBe(true);
  await expect.poll(() => crawlState(page)).toBe("done");
  expect(starts(w, "c-005")).toBe(1);
  expect(starts(w, "c-006")).toBe(1);
  expect(w.log.indexOf("start c-006")).toBeGreaterThan(
    w.log.indexOf("end c-005"),
  );
  for (let i = 0; i < 9; i++) expect(await available(page, i)).toBe(true);
});

test("the crawl rests once some three megabytes of text lie ahead of the reader, and a move that leaves that much ahead does not set it off", async ({
  page,
}) => {
  const w = await wire(page);
  // Two long chapters past what the prefetch reaches.
  w.pad("c-005", 1.6 * MB);
  w.pad("c-006", 1.6 * MB);
  await open(page);
  await expect.poll(() => crawlState(page)).toBe("full");
  expect((await crawl(page)).ahead).toBeGreaterThanOrEqual(3 * MB);
  expect(await available(page, 5)).toBe(true);
  expect(await available(page, 6)).toBe(false);
  expect(starts(w, "c-007")).toBe(0);

  // Two chapters on, the prefetch's own reach ends on the last chapter
  // held, and as much text is still ahead: the crawl stands aside for
  // the move (`yielding`) and comes back to its rest.
  await goTo(page, 2);
  await expect.poll(() => crawlState(page)).toBe("full");
  expect(await available(page, 6)).toBe(false);
  expect(starts(w, "c-007")).toBe(0);
});

test("a resting crawl sets off again when reading has used up most of what was ahead", async ({
  page,
}) => {
  const w = await wire(page);
  // Two long chapters right after the first: what the prefetch brings on
  // opening is already more than the crawl would hold.
  w.pad("c-002", 1.6 * MB);
  w.pad("c-003", 1.6 * MB);
  await open(page);
  await expect.poll(() => crawlState(page)).toBe("full");
  expect(await available(page, 3)).toBe(true);
  expect(await available(page, 4)).toBe(false);

  // One chapter on, a megabyte and a half is still ahead: the prefetch
  // takes its one more section, the crawl nothing.
  await goTo(page, 1);
  await expect.poll(() => crawlState(page)).toBe("full");
  expect(await available(page, 4)).toBe(true);
  expect(await available(page, 5)).toBe(false);

  // Past the long chapters there is little left ahead: the prefetch
  // reaches the sixth chapter, and the rest is the crawl's again.
  await goTo(page, 2);
  await expect.poll(() => available(page, 8)).toBe(true);
  await expect.poll(() => crawlState(page)).toBe("done");
  for (const c of ["c-007", "c-008", "c-009"]) expect(starts(w, c)).toBe(1);
});

{
  test("a browser that asks for data to be saved gets only what the reader reaches for", async ({
    page,
  }) => {
    const w = await wire(page);
    await connection(page, { saveData: true });
    await open(page);
    await expect.poll(() => available(page, 3)).toBe(true);
    await expect.poll(() => crawlState(page)).toBe("withheld");
    expect(await available(page, 4)).toBe(false);
    expect(starts(w, "c-005")).toBe(0);

    // A move asks again, and is answered the same.
    await goTo(page, 1);
    await expect.poll(() => available(page, 4)).toBe(true);
    await expect.poll(() => crawlState(page)).toBe("withheld");
    expect(await available(page, 5)).toBe(false);
    expect(starts(w, "c-006")).toBe(0);
  });
}

test("a cellular connection that does not ask for data to be saved is fetched over like any other", async ({
  page,
}) => {
  await wire(page);
  await connection(page, { saveData: false, type: "cellular" });
  await open(page);
  await expect.poll(() => crawlState(page)).toBe("done");
  expect(await available(page, 8)).toBe(true);
});

test("a request that fails is the crawl's last until the connection is back", async ({
  page,
  context,
}) => {
  const w = await wire(page);
  const release = w.hold("c-005");
  await open(page);
  await expect.poll(() => fetching(page)).toBe("c-005");

  await context.setOffline(true);
  release();
  await expect.poll(() => crawlState(page)).toMatch(/^(failed|offline)$/);
  expect(await available(page, 4)).toBe(false);
  expect(starts(w, "c-005")).toBe(1);
  expect(starts(w, "c-006")).toBe(0);

  await context.setOffline(false);
  await expect.poll(() => available(page, 8)).toBe(true);
  await expect.poll(() => crawlState(page)).toBe("done");
  expect(starts(w, "c-005")).toBe(2);
});

test("while the document is hidden nothing more is fetched; shown again, the crawl goes on", async ({
  page,
}) => {
  const w = await wire(page);
  const release = w.hold("c-005");
  await open(page);
  await expect.poll(() => fetching(page)).toBe("c-005");

  await page.evaluate(() =>
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    }),
  );
  release();
  await expect.poll(() => crawlState(page)).toBe("hidden");
  expect(await available(page, 4)).toBe(true);
  expect(starts(w, "c-006")).toBe(0);

  await page.evaluate(() => {
    delete (document as unknown as { visibilityState?: string })
      .visibilityState;
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => available(page, 8)).toBe(true);
  await expect.poll(() => crawlState(page)).toBe("done");
});

test("leaving the reader ends the crawl: what it was out for is the last request", async ({
  page,
  context,
}) => {
  const w = await wire(page);
  const release = w.hold("c-005");
  await open(page);
  await expect.poll(() => fetching(page)).toBe("c-005");
  await page.evaluate(() => {
    const w = window as unknown as { __left: unknown };
    w.__left = window.__beepubReaderNG.core;
  });

  await showBar(page, context);
  await page.getByRole("button", { name: "Back to book detail" }).click();
  await expect(page).not.toHaveURL(/\/read/);
  // The reader's engine is torn down, the prefetcher with it.
  expect(
    await page.evaluate(
      () => (window as unknown as { __left: { crawl: unknown } }).__left.crawl,
    ),
  ).toBeNull();

  release();
  await expect.poll(() => w.log).toContain("end c-005");
  // (Nothing says "and no more" but time: several of the crawl's pauses.)
  await page.waitForTimeout(1500);
  expect(starts(w, "c-006")).toBe(0);
});
