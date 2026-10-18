import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { CASE_FOLDED_BOOK, openBook, seedFixture } from "./ng-helpers";

/**
 * A book made on a case-insensitive file system names its files in the
 * OPF in another letter case than its zip holds them, and lists files
 * that are not there at all. Other readers open it; the upload takes it
 * (seedFixture uploads through the API), and the reader shows it with its
 * own stylesheet.
 */

test.use({ storageState: ADMIN_STATE });

test("a book whose OPF names its files in another letter case is taken, and read with its stylesheet", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, CASE_FOLDED_BOOK);
  await openBook(page, bookId, {}, CASE_FOLDED_BOOK);
  const color = await page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    return getComputedStyle(doc.querySelector("p.first")!).color;
  });
  expect(color).toBe("rgb(1, 2, 3)");
});
