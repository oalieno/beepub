import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { TXT_BOOK, openBook, seedFixture } from "./ng-helpers";

/**
 * TXT upload: the file is converted to a chaptered EPUB at ingest (parts
 * nest chapters in the TOC, the header lines become title and author), the
 * reader opens that EPUB, and the detail page offers the original file.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

const chrome = (page: Page) => page.getByTestId("ng-chrome");

/** Text of the section on screen (the iframe lives in a closed shadow
 *  root, so it is read through the debug handle). */
function sectionText(page: Page) {
  return page.evaluate(
    () =>
      (window.__beepubReaderNG.core.getContents()[0].doc as Document).body
        ?.textContent ?? "",
  );
}

test("a TXT upload becomes a chaptered book the reader opens", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, TXT_BOOK);

  const book = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(book.format).toBe("txt");
  expect(book.epub_title).toBe(TXT_BOOK.title);
  expect(book.epub_authors).toEqual(["林未晞"]);
  expect(book.epub_language).toBe("zh-TW");

  // /file is an EPUB; /original is the uploaded text.
  const file = await page.request.get(`/api/books/${bookId}/file`);
  expect(file.headers()["content-type"]).toBe("application/epub+zip");
  expect((await file.body()).subarray(0, 2).toString()).toBe("PK");
  const original = await page.request.get(`/api/books/${bookId}/original`);
  expect(original.headers()["content-disposition"]).toContain("attachment");
  expect((await original.body()).toString("utf-8")).toContain("作者：林未晞");

  await openBook(page, bookId, {}, TXT_BOOK);
  await page.getByRole("button", { name: "Table of Contents" }).click();
  const dialog = page.getByRole("dialog", { name: "Table of Contents" });
  await expect(dialog).toBeVisible();
  // Parts nest their chapters; the TOC listing at the top of the file
  // did not become chapters of its own.
  await expect(dialog.getByRole("button", { name: "第一卷 潮聲" })).toHaveCount(
    1,
  );
  await expect(dialog.getByRole("button", { name: "第一章 退潮" })).toHaveCount(
    1,
  );
  await dialog.getByRole("button", { name: "第三章 信" }).click();
  await expect(dialog).toBeHidden();
  await expect(chrome(page)).toContainText("第三章 信");
  await expect.poll(() => sectionText(page)).toContain("信是用海水寫的");
});

test("the detail page offers the original TXT", async ({ page }) => {
  const bookId = await seedFixture(page.request, TXT_BOOK);
  await page.goto(`/books/${bookId}`);
  await expect(
    page.getByRole("button", { name: "Imported from TXT" }),
  ).toBeVisible();

  await page.getByTitle("More actions").click();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Download original TXT" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toMatch(/\.txt$/);
});
