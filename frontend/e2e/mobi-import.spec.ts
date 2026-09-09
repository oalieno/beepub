import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { AZW3_BOOK, MOBI7_BOOK, openBook, seedFixture } from "./ng-helpers";

/**
 * MOBI/AZW3 upload: the file is converted to an EPUB at ingest (KF8 unpacks
 * to one, old MOBI7 is split on its page breaks), the reader opens that
 * EPUB with its TOC and images, and the detail page offers the original.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

const chrome = (page: Page) => page.getByTestId("ng-chrome");

function sectionText(page: Page) {
  return page.evaluate(
    () =>
      (window.__beepubReaderNG.core.getContents()[0].doc as Document).body
        ?.textContent ?? "",
  );
}

/** Whether the section on screen shows a decoded image. */
function sectionImageLoaded(page: Page) {
  return page.evaluate(() => {
    const doc = window.__beepubReaderNG.core.getContents()[0].doc as Document;
    const img = doc.images[0];
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function openChapter(page: Page, name: string) {
  await page.getByRole("button", { name: "Table of Contents" }).click();
  const dialog = page.getByRole("dialog", { name: "Table of Contents" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name }).click();
  await expect(dialog).toBeHidden();
  await expect(chrome(page)).toContainText(name);
}

test("an AZW3 upload becomes an EPUB with cover, TOC and images", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, AZW3_BOOK);

  const book = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(book.format).toBe("azw3");
  expect(book.epub_title).toBe(AZW3_BOOK.title);
  expect(book.epub_authors).toEqual(["林秋水"]);
  expect(book.epub_isbn).toBeNull();
  expect(book.cover_path).not.toBeNull();

  const file = await page.request.get(`/api/books/${bookId}/file`);
  expect(file.headers()["content-type"]).toBe("application/epub+zip");
  expect((await file.body()).subarray(0, 2).toString()).toBe("PK");
  const original = await page.request.get(`/api/books/${bookId}/original`);
  expect(original.headers()["content-disposition"]).toContain("attachment");
  // A Palm database: the type stamp "BOOKMOBI" sits at byte 60.
  expect((await original.body()).subarray(60, 68).toString()).toBe("BOOKMOBI");

  await openBook(page, bookId, {}, AZW3_BOOK);
  await openChapter(page, "第二章 沒有地址的信");
  await expect.poll(() => sectionText(page)).toContain("郵差把信放進口袋");
  await expect.poll(() => sectionImageLoaded(page)).toBe(true);
});

test("an old MOBI upload is split into chapters the reader opens", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, MOBI7_BOOK);

  const book = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(book.format).toBe("mobi");
  expect(book.epub_title).toBe(MOBI7_BOOK.title);
  expect(book.epub_authors).toEqual(["周硯"]);
  expect(book.cover_path).not.toBeNull();

  await openBook(page, bookId, {}, MOBI7_BOOK);
  await openChapter(page, "第二章 竹籃");
  await expect.poll(() => sectionText(page)).toContain("同一枚舊郵票");
  await expect.poll(() => sectionImageLoaded(page)).toBe(true);
  await openChapter(page, "第三章 對岸");
  await expect.poll(() => sectionText(page)).toContain("投進了河裡");
});

test("the detail page offers the original AZW3", async ({ page }) => {
  const bookId = await seedFixture(page.request, AZW3_BOOK);
  await page.goto(`/books/${bookId}`);
  await expect(
    page.getByRole("button", { name: "Imported from AZW3" }),
  ).toBeVisible();

  await page.getByTitle("More actions").click();
  const downloadEvent = page.waitForEvent("download");
  await page
    .getByRole("menuitem", { name: "Download original AZW3" })
    .click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toMatch(/\.azw3$/);
});
