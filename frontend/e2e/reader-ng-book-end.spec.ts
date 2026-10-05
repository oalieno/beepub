import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  NOTES_BOOK,
  VERTICAL_MIXED_BOOK,
  openBook,
  seedFixture,
} from "./ng-helpers";

/**
 * reader-ng: what happens at the end of a book. Turning past the last
 * page opens the finish overlay, reaching the last page marks the book
 * finished (with undo in the overlay), and a book in a series offers the
 * next volume instead — all route logic the current reader has, now on
 * the new engine.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(90_000);

const SERIES = "Harbour Ledger Cycle";

async function setSeries(
  page: Page,
  bookId: string,
  series: string | null,
  index: number | null,
) {
  const res = await page.request.put(`/api/books/${bookId}/metadata`, {
    data: { series, series_index: index },
  });
  expect(res.ok()).toBeTruthy();
}

/** Back to "never started": the auto-mark only fires from none or
 *  want_to_read, and earlier runs leave the fixture finished. */
async function resetStatus(page: Page, bookId: string) {
  const res = await page.request.put(`/api/books/${bookId}/reading-status`, {
    data: { reading_status: null, started_at: null, finished_at: null },
  });
  expect(res.ok()).toBeTruthy();
}

async function readingStatus(page: Page, bookId: string) {
  const res = await page.request.get(`/api/books/${bookId}/interaction`);
  return (await res.json()).reading_status as string | null;
}

/** Jump to the last section, then turn forward until the reader reports
 *  the end of the book (the toolbar button goes through the component,
 *  where the last page's turn becomes the book-end signal). */
async function turnPastTheEnd(page: Page) {
  await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    return core.goTo(core.lastLinearIndex());
  });
  await page.waitForTimeout(400);
  const next = page.getByRole("button", { name: "Next page" });
  const overlay = page.getByTestId("book-end");
  for (let i = 0; i < 30 && !(await overlay.isVisible()); i++) {
    await next.click();
    // The paginator holds a 100ms lock after each turn.
    await page.waitForTimeout(300);
  }
  await expect(overlay).toBeVisible();
  return overlay;
}

test("turning past the last page opens the finish overlay and marks the book finished, with undo", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, NOTES_BOOK);
  await setSeries(page, bookId, null, null);
  await resetStatus(page, bookId);
  await openBook(page, bookId, {}, NOTES_BOOK);

  const overlay = await turnPastTheEnd(page);
  await expect(overlay.getByText("You finished this book")).toBeVisible();
  await expect(overlay.getByText(NOTES_BOOK.title)).toBeVisible();

  // Reaching the last page marked it finished; the overlay says so and
  // offers the way back.
  await expect(overlay.getByText("Marked as finished")).toBeVisible();
  await expect.poll(() => readingStatus(page, bookId)).toBe("read");
  await overlay.getByRole("button", { name: "Undo" }).click();
  await expect(overlay.getByText("Finished mark removed")).toBeVisible();
  await expect.poll(() => readingStatus(page, bookId)).toBeNull();

  // Escape puts the overlay away; the page stays where it was.
  await page.keyboard.press("Escape");
  await expect(overlay).toBeHidden();
  expect(
    await page.evaluate(() => window.__beepubReaderNG.core.lastLocation.index),
  ).toBe(
    await page.evaluate(() => window.__beepubReaderNG.core.lastLinearIndex()),
  );
});

test("the end of a series volume offers the next one", async ({ page }) => {
  const bookId = await seedFixture(page.request, NOTES_BOOK);
  const nextId = await seedFixture(page.request, VERTICAL_MIXED_BOOK);
  await setSeries(page, bookId, SERIES, 1);
  await setSeries(page, nextId, SERIES, 2);
  try {
    await resetStatus(page, bookId);
    await openBook(page, bookId, {}, NOTES_BOOK);

    const overlay = await turnPastTheEnd(page);
    await expect(overlay.getByText(`Up next in ${SERIES}`)).toBeVisible();
    await expect(overlay.getByText(VERTICAL_MIXED_BOOK.title)).toBeVisible();
    await expect(overlay.getByText("Book 2 of 2")).toBeVisible();

    // "Start reading" opens the next volume in this same reader.
    // The app is not reloaded (that would replay its launch animation):
    // a mark left on the window survives, and the reader is a fresh one.
    await page.evaluate(() => {
      const w = window as unknown as Record<string, unknown>;
      w.__sameDocument = true;
      w.__previousCore = window.__beepubReaderNG.core;
    });
    await overlay.getByRole("button", { name: "Start reading" }).click();
    await page.waitForURL(new RegExp(`/books/${nextId}/read`));
    await page.waitForFunction(
      () => {
        const w = window as unknown as Record<string, unknown>;
        const core = window.__beepubReaderNG?.core;
        return !!core?.lastLocation && core !== w.__previousCore;
      },
      null,
      { timeout: 30_000 },
    );
    expect(
      await page.evaluate(
        () => (window as unknown as Record<string, unknown>).__sameDocument,
      ),
    ).toBe(true);
    await expect(page.getByTestId("book-end")).toBeHidden();
    await expect(page).toHaveTitle(new RegExp(VERTICAL_MIXED_BOOK.title));
  } finally {
    await setSeries(page, bookId, null, null);
    await setSeries(page, nextId, null, null);
  }
});
