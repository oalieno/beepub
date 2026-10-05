import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  CHAPTERS_BOOK,
  PLATES_BOOK,
  openBook,
  resetProgress,
  seedBook,
  seedFixture,
  seedGesturesSeen,
} from "./ng-helpers";

/**
 * reader-ng G2 ②: reading progress on the new engine — restore to the
 * saved CFI, saves on page turns (the same wire the current reader
 * writes), the weight-interpolated percentage and the scrubber seek on
 * its scale, the percentage fallback when a stored CFI stopped
 * resolving, and the peek semantics of an explicit jump target.
 */

test.use({ storageState: ADMIN_STATE });
// The first open after a stack switch pays vite's cold transform.
test.setTimeout(60_000);

// The fixture is shared with the selection specs (both readers'), which
// assume it opens on its first page: leave its progress there.
test.afterEach(async ({ page }) => {
  await resetProgress(page.request, await seedBook(page.request));
});

/** The worker extracts text shortly after upload; weights ride the book
 *  detail. Until then the reader falls back to uniform weights. The
 *  extraction queues behind earlier uploads' metadata fetches (seconds
 *  each, external sources), so a fresh database can take a minute. */
async function waitForWeights(page: Page, bookId: string): Promise<number[]> {
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/books/${bookId}`)).json())
          .section_weights,
      { timeout: 120_000, message: "text extraction never produced weights" },
    )
    .not.toBeNull();
  return (await (await page.request.get(`/api/books/${bookId}`)).json())
    .section_weights;
}

function location(page: Page) {
  return page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return {
      index: l.index as number,
      fraction: l.fraction as number,
      size: l.size as number,
      // The saved position: a point CFI where the visible text starts.
      cfi: l.startCfi as string,
      reason: l.reason as string,
    };
  });
}

function docHasText(page: Page, text: string) {
  return page.evaluate((t) => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    return doc.body?.textContent?.includes(t) ?? false;
  }, text);
}

/** The chrome's percentage — the desktop toolbar and the phone top bar
 *  both render one; only the current layout's is visible. */
function percentInChrome(page: Page) {
  return page.locator('[data-testid="reader-percent"]:visible');
}

async function readPercent(page: Page): Promise<number> {
  const text = await percentInChrome(page).textContent();
  return parseInt(text ?? "0", 10);
}

function progressPut(page: Page) {
  return page.waitForResponse(
    (r) => r.request().method() === "PUT" && r.url().endsWith("/progress"),
    { timeout: 10_000 },
  );
}

async function getProgress(page: Page, bookId: string) {
  return (await page.request.get(`/api/books/${bookId}/progress`)).json();
}

async function turnPages(page: Page, n: number) {
  for (let i = 0; i < n; i++) {
    await page.keyboard.press("ArrowRight");
    // The paginator holds a 100ms lock after each turn.
    await page.waitForTimeout(250);
  }
}

test("page turns save the position and a reopen restores it", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);
  // Land on a known page first: the fixture may carry progress from an
  // earlier run of this suite.
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(0));
  await page.waitForTimeout(300);

  const saved = progressPut(page);
  await turnPages(page, 3);
  expect((await saved).ok()).toBeTruthy();
  const here = await location(page);
  expect(here.reason).toBe("page");
  expect(here.fraction).toBeGreaterThan(0);

  const row = await getProgress(page, bookId);
  expect(row.cfi).toBe(here.cfi);
  expect(row.section_index).toBe(0);
  expect(row.percentage).toBeGreaterThan(0);
  expect(row.section_page).toBe(Math.round(here.fraction / here.size) + 1);
  expect(await readPercent(page)).toBe(Math.round(row.percentage));

  // Same geometry → the restore lands on the same page.
  await openBook(page, bookId, { restore: "1" });
  const back = await location(page);
  expect(back.index).toBe(0);
  expect(back.fraction).toBeCloseTo(here.fraction, 3);
  // The restore's navigation, possibly re-anchored once by a late font
  // load — never a user move.
  expect(["navigation", "anchor"]).toContain(back.reason);
  expect(await readPercent(page)).toBe(Math.round(row.percentage));
});

test("a jump over sections never opened still saves", async ({ page }) => {
  const bookId = await seedFixture(page.request, PLATES_BOOK);
  // No page counts on record: the sections skipped below have none.
  await resetProgress(page.request, bookId);
  try {
    await openBook(page, bookId, {}, PLATES_BOOK);
    const saved = progressPut(page);
    const last = await page.evaluate(() => {
      const core = window.__beepubReaderNG.core;
      const index = core.lastLinearIndex();
      void core.goTo(index);
      return index;
    });
    expect(last).toBeGreaterThan(1);
    // The skipped sections go out as 0 (unknown), not as holes the
    // server refuses — which left the old position on record.
    const response = await saved;
    expect(response.status()).toBe(200);
    const row = await getProgress(page, bookId);
    expect(row.section_index).toBe(last);
    expect(row.section_page_counts.slice(1, last)).toEqual(
      new Array(last - 1).fill(0),
    );
  } finally {
    await resetProgress(page.request, bookId);
  }
});

test("a stored CFI that no longer resolves degrades to the stored percentage", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  // A section step that exists with an in-document path that doesn't —
  // what a calibre rewrite leaves behind.
  const stored = await page.request.put(`/api/books/${bookId}/progress`, {
    data: {
      cfi: "epubcfi(/6/2!/4/999/1:0)",
      percentage: 60,
      section_index: 0,
    },
  });
  expect(stored.ok()).toBeTruthy();

  await openBook(page, bookId, { restore: "1" });
  await expect(page.getByText("resumed near 60%")).toBeVisible();
  const here = await location(page);
  expect(here.index).toBe(0);
  expect(here.fraction).toBeGreaterThan(0.3);
  expect(here.fraction).toBeLessThan(0.9);
  // The recovered position is persisted in place of the dead one.
  await expect
    .poll(async () => (await getProgress(page, bookId)).cfi, {
      timeout: 10_000,
    })
    .toBe(here.cfi);
});

test("percentage follows the weights and the scrubber seeks on their scale", async ({
  page,
}) => {
  test.slow(); // the first run on a fresh database waits for extraction
  const bookId = await seedFixture(page.request, CHAPTERS_BOOK);
  const weights = await waitForWeights(page, bookId);
  await resetProgress(page.request, bookId);
  expect(weights.filter((w) => w > 0)).toHaveLength(2);
  const total = weights.reduce((a, b) => a + b, 0);
  let before = 0;
  for (let i = 0; i < weights.length - 1; i++) before += weights[i]!;
  const chapter2Start = (before / total) * 100;
  expect(chapter2Start).toBeGreaterThan(80); // the fixture's 15:1 shape

  await seedGesturesSeen(page);
  await page.goto(`/books/${bookId}/read`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await expect.poll(() => docHasText(page, "甲章首段")).toBe(true);
  await expect(percentInChrome(page)).toBeVisible();

  // Degenerate-fragmentation guard (no CJK fonts → one giant page).
  const first = await location(page);
  const pages = first.size ? Math.round(1 / first.size) : 1;
  test.skip(pages < 3, "vertical fragmentation degenerate — CJK fonts missing");

  // vertical-rl: ArrowLeft pages forward. Progress must be monotone and
  // actually advance.
  let last = await readPercent(page);
  const initial = last;
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press("ArrowLeft");
    await page.waitForTimeout(300);
    const now = await readPercent(page);
    expect(now).toBeGreaterThanOrEqual(last);
    last = now;
  }
  expect(last).toBeGreaterThan(initial);

  // The scrubber stays in the DOM while the bottom bar is folded; drive
  // it directly — this is about the weight mapping, not the hover.
  const scrubber = page.getByTestId("ng-progress").locator("input[type=range]");
  await expect(scrubber).toBeAttached();
  const target = Math.min(99, Math.ceil(chapter2Start) + 2);
  await scrubber.evaluate((el, value) => {
    const input = el as HTMLInputElement;
    input.value = String(value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, target);
  await expect
    .poll(() => docHasText(page, "乙章開場"), { timeout: 15_000 })
    .toBe(true);
  expect((await location(page)).index).toBe(weights.length - 1);

  // Chapter ticks share the weight scale with the seek mapping: one gap on
  // the chapter 2 boundary.
  await expect(scrubber).toHaveAttribute("data-ticks", /./);
  const ticks = (await scrubber.getAttribute("data-ticks"))!
    .split(",")
    .map(parseFloat);
  expect(ticks).toHaveLength(1);
  expect(Math.abs(ticks[0]! - chapter2Start)).toBeLessThan(0.5);
});

test("an explicit ?cfi= is a visit: progress stays put until the reader moves on", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(0));
  await page.waitForTimeout(300);
  const saved = progressPut(page);
  await turnPages(page, 3);
  await saved;
  const home = await location(page);
  const homeRow = await getProgress(page, bookId);
  expect(homeRow.cfi).toBe(home.cfi);

  // Visit the first word of the section (page 1) — a highlight click.
  await openBook(page, bookId, { cfi: "epubcfi(/6/2!/4/4,/1:13,/1:22)" });
  const visit = await location(page);
  expect(visit.fraction).toBeLessThan(home.fraction);
  const pill = page.getByTestId("ng-peek-return");
  await expect(pill).toBeVisible();
  await expect(pill).toContainText(`${Math.round(homeRow.percentage)}%`);

  // Nothing is written while the visit lasts (the debounce is 2s).
  await page.waitForTimeout(3500);
  expect((await getProgress(page, bookId)).cfi).toBe(home.cfi);

  // The way back lands on the saved page and ends the visit.
  await pill.click();
  await expect.poll(() => location(page)).toMatchObject({ index: 0 });
  expect((await location(page)).fraction).toBeCloseTo(home.fraction, 3);
  await expect(pill).toBeHidden();

  // Reading on from a visit makes the new place the position.
  await openBook(page, bookId, { cfi: "epubcfi(/6/2!/4/4,/1:13,/1:22)" });
  const moved = progressPut(page);
  await turnPages(page, 1);
  expect((await moved).ok()).toBeTruthy();
  const after = await location(page);
  expect(after.cfi).not.toBe(home.cfi);
  await expect
    .poll(async () => (await getProgress(page, bookId)).cfi)
    .toBe(after.cfi);
});
