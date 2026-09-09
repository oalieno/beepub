import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  CBZ_BOOK,
  openComic,
  pagerState,
  seedFixture,
  setPagerSetting,
} from "./ng-helpers";

/**
 * The image pager: a pre-paginated book (here a comic packed from a CBZ:
 * six pages, right-to-left, page four a two-page spread) is claimed from
 * BookReader before it renders and drawn as images. Wide screens pair
 * portrait pages; the cover and the wide page stand alone. Position is
 * the page, saved as a CFI the current reader restores from too.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

const chrome = (page: Page) => page.getByTestId("ng-chrome");

async function settleSave(page: Page) {
  // The pager debounces its save by two seconds after a move.
  await page.waitForTimeout(2600);
}

test("double page: cover alone, then pairs, the spread alone", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await openComic(page, bookId);
  // Start from the cover whatever an earlier run left behind.
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));
  let state = await pagerState(page);
  expect(state.mode).toBe("single");
  expect(state.shown).toEqual([0]);
  await setPagerSetting(page, "setting-pager-mode", "Double page");

  state = await pagerState(page);
  expect(state.total).toBe(6);
  expect(state.twoPage).toBe(true);
  expect(state.rtl).toBe(true);
  expect(state.shown).toEqual([0]);
  await expect(chrome(page)).toContainText("1 / 6");
  expect(state.cfi).toMatch(/^epubcfi\(\/6\/2(\[[^\]]*\])?!\/4\)$/);

  // Pages 2+3 pair; right-to-left puts page 2 on the right.
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  state = await pagerState(page);
  expect(state.shown).toEqual([2, 1]);
  await expect(chrome(page)).toContainText("2–3 / 6");
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.pager.loaded))
    .toBe(true);
  const images = page.locator('[data-testid="image-pager"] img');
  await expect(images).toHaveCount(2);
  for (const img of await images.all()) {
    expect(
      await img.evaluate((el: HTMLImageElement) => el.naturalWidth),
    ).toBeGreaterThan(0);
  }

  // The wide page (4) stands alone, then 5+6 pair.
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  expect((await pagerState(page)).shown).toEqual([3]);
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  expect((await pagerState(page)).shown).toEqual([5, 4]);
  await expect(chrome(page)).toContainText("5–6 / 6");

  // Past the last page: the book-end overlay, no move.
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  await expect(page.getByTestId("book-end")).toBeVisible();
  expect((await pagerState(page)).page).toBe(4);
  await page.keyboard.press("Escape");

  // Forcing the direction flips the pair on screen; back to single.
  await setPagerSetting(page, "setting-pager-direction", "Left to right");
  state = await pagerState(page);
  expect(state.rtl).toBe(false);
  expect(state.shown).toEqual([4, 5]);
  await setPagerSetting(page, "setting-pager-direction", "As the book");
  await setPagerSetting(page, "setting-pager-mode", "Single page");
  expect((await pagerState(page)).shown).toEqual([4]);
});

test("the page is the position: it restores here and in the current reader", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await openComic(page, bookId);
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(3));
  await settleSave(page);

  const saved = await (
    await page.request.get(`/api/books/${bookId}/progress`)
  ).json();
  expect(saved.cfi).toMatch(/^epubcfi\(\/6\/8(\[[^\]]*\])?!\/4\)$/);
  expect(saved.percentage).toBe(60);
  expect(saved.current_page).toBe(4);
  expect(saved.total_pages).toBe(6);

  await openComic(page, bookId);
  expect((await pagerState(page)).page).toBe(3);

  // The current reader reads the same CFI as spine item four.
  await page.goto(`/books/${bookId}/read`);
  await page.waitForFunction(
    () => {
      try {
        const loc = (
          window as any
        ).__beepubReader?.rendition?.currentLocation?.();
        return !!loc?.start?.cfi;
      } catch {
        return false;
      }
    },
    null,
    { timeout: 30_000 },
  );
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as any).__beepubReader.rendition.currentLocation().start
            .index,
      ),
    )
    .toBe(3);
});

test("the scroll flow stacks the pages and follows the scroll", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await openComic(page, bookId);
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));

  await setPagerSetting(page, "setting-pager-mode", "Vertical scroll");
  await expect(page.getByTestId("image-pager")).toHaveAttribute(
    "data-flow",
    "scroll",
  );
  expect((await pagerState(page)).twoPage).toBe(false);

  const scroller = page.locator('[data-testid="image-pager"] > div');
  await scroller.evaluate((el) => (el.scrollTop = el.scrollHeight));
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(5);
  await expect(chrome(page)).toContainText("6 / 6");

  // Back to pages for the specs that follow; the choice is remembered.
  await setPagerSetting(page, "setting-pager-mode", "Single page");
  await expect(page.getByTestId("image-pager")).toHaveAttribute(
    "data-flow",
    "paged",
  );
  expect((await pagerState(page)).page).toBe(5);
});

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test("single pages; the left tap zone turns forward in a right-to-left book", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, CBZ_BOOK);
    await openComic(page, bookId);
    await page.evaluate(() => window.__beepubReaderNG.pager.goTo(1));
    let state = await pagerState(page);
    expect(state.twoPage).toBe(false);
    expect(state.shown).toEqual([1]);

    const pager = page.getByTestId("image-pager");
    const box = (await pager.boundingBox())!;
    // Left quarter: forward (the next page sits to the left in manga).
    await page.mouse.click(box.x + box.width * 0.1, box.y + box.height / 2);
    expect((await pagerState(page)).page).toBe(2);
    // Right quarter: back.
    await page.mouse.click(box.x + box.width * 0.9, box.y + box.height / 2);
    expect((await pagerState(page)).page).toBe(1);
    // Arrow keys follow the screen, not the reading order.
    await page.keyboard.press("ArrowLeft");
    expect((await pagerState(page)).page).toBe(2);
    await page.keyboard.press("ArrowRight");
    expect((await pagerState(page)).page).toBe(1);

    // A double tap zooms in and a page turn resets it.
    await page.mouse.dblclick(box.x + box.width / 2, box.y + box.height / 2);
    state = await pagerState(page);
    expect(state.scale).toBeGreaterThan(1);
    expect(state.page).toBe(1);
    await page.keyboard.press("ArrowLeft");
    state = await pagerState(page);
    expect(state.scale).toBe(1);
    expect(state.page).toBe(2);
  });
});
