import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  HORIZONTAL_VERTICAL_COLOPHON_BOOK,
  VERTICAL_PLATES_FIRST_BOOK,
  resetProgress,
  seedFixture,
  seedGesturesSeen,
  type Fixture,
} from "./ng-helpers";

/**
 * reader-ng: a CJK book is laid out in one writing mode throughout, the
 * one its heaviest section is written in, settled before the first page
 * paints — whatever page it opens on, and however the book's own sheets
 * differ from section to section. Nothing is stored for it.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(90_000);

/** The writing mode the core lays the book out in, and what the section
 *  on screen is. */
function engine(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    return {
      index: core.lastLocation.index as number,
      forced: core.forcedWritingMode() as string | null,
      vertical: core.vertical as boolean,
      leftward: core.advancesLeftward() as boolean,
      body: getComputedStyle(doc.body).writingMode,
    };
  });
}

/** Seed the fixture and wait for the library to have read it: its
 *  section sizes are what the mode is settled by. */
async function seedExtracted(page: Page, fixture: Fixture) {
  const bookId = await seedFixture(page.request, fixture);
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/books/${bookId}`)).json())
          .section_weights?.length ?? 0,
      { timeout: 60_000 },
    )
    .toBeGreaterThan(0);
  return bookId;
}

/** Open the book on section `index` and read the engine as soon as the
 *  first page is there. */
async function openOn(
  page: Page,
  bookId: string,
  index: number,
  query: Record<string, string> = {},
) {
  await seedGesturesSeen(page);
  const params = new URLSearchParams({
    turn: "instant",
    cfi: `epubcfi(/6/${(index + 1) * 2}!/4/2)`,
    ...query,
  });
  await page.goto(`/books/${bookId}/read?${params}`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  return engine(page);
}

const VERTICAL = {
  forced: "vertical",
  vertical: true,
  leftward: true,
  body: "vertical-rl",
};

test("a vertical book that opens on horizontal plates is vertical from its first page, wherever it is opened", async ({
  page,
}) => {
  const bookId = await seedExtracted(page, VERTICAL_PLATES_FIRST_BOOK);
  expect(await openOn(page, bookId, 0)).toEqual({ index: 0, ...VERTICAL });
  expect(await openOn(page, bookId, 2)).toEqual({ index: 2, ...VERTICAL });
  // The colophon too, and the way back to the plate turns the same way.
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(4));
  await expect.poll(async () => (await engine(page)).index).toBe(4);
  expect(await engine(page)).toEqual({ index: 4, ...VERTICAL });
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
  await expect.poll(async () => (await engine(page)).index).toBe(1);
  expect(await engine(page)).toEqual({ index: 1, ...VERTICAL });
  await resetProgress(page.request, bookId);
});

test("the strip opened on a plate of a vertical book runs leftward", async ({
  page,
}) => {
  const bookId = await seedExtracted(page, VERTICAL_PLATES_FIRST_BOOK);
  await openOn(page, bookId, 0, { turn: "scroll" });
  await expect
    .poll(() =>
      page.evaluate(() => window.__beepubReaderNG.core.strip?.pinnedIndex),
    )
    .toBe(0);
  expect(
    await page.evaluate(() => window.__beepubReaderNG.core.strip.vertical),
  ).toBe(true);
  expect(await engine(page)).toEqual({ index: 0, ...VERTICAL });
  await resetProgress(page.request, bookId);
});

test("without the book's record in time, the book still opens in one mode, the same on a plate and in a chapter", async ({
  page,
}) => {
  const bookId = await seedExtracted(page, VERTICAL_PLATES_FIRST_BOOK);
  // The record (its section sizes) comes after the reader has stopped
  // waiting for it: the mode is read from the book's first section and
  // its manifest's sheets.
  // Which open the record answered last (an earlier page's request may
  // still be held while the next one opens).
  let opening = 0;
  let answered = 0;
  await page.route(`**/api/books/${bookId}`, async (route) => {
    const asked = opening;
    await new Promise((resolve) => setTimeout(resolve, 6000));
    answered = asked;
    await route.continue().catch(() => {});
  });
  for (const index of [0, 2]) {
    opening += 1;
    expect(await openOn(page, bookId, index)).toEqual({
      index,
      ...VERTICAL,
    });
    // (Open, and read, before this open's record came.)
    expect(answered).toBeLessThan(opening);
  }
  await page.unroute(`**/api/books/${bookId}`);
  await resetProgress(page.request, bookId);
});

test("a horizontal book with a vertical colophon sheet is horizontal throughout and turns rightward", async ({
  page,
}) => {
  const bookId = await seedExtracted(page, HORIZONTAL_VERTICAL_COLOPHON_BOOK);
  const horizontal = {
    forced: "horizontal",
    vertical: false,
    leftward: false,
    body: "horizontal-tb",
  };
  expect(await openOn(page, bookId, 0)).toEqual({ index: 0, ...horizontal });
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(2));
  await expect.poll(async () => (await engine(page)).index).toBe(2);
  expect(await engine(page)).toEqual({ index: 2, ...horizontal });
  await resetProgress(page.request, bookId);
});
