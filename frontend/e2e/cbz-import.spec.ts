import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { CBZ_BOOK, seedFixture } from "./ng-helpers";

/**
 * CBZ upload: the archive is packed into a pre-paginated EPUB at ingest
 * (one fixed-layout page per image, right-to-left when ComicInfo says so),
 * classified an image book on the spot, and its pages are served in
 * reading order for the pager. The current reader opens it through
 * epub.js's fixed-layout path; the detail page offers the original.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

/** Whether the current reader shows a decoded image in its first section. */
function currentReaderImageLoaded(page: Page) {
  return page.evaluate(() => {
    const contents = (window as any).__beepubReader?.rendition?.getContents?.();
    const doc = contents?.[0]?.document as Document | undefined;
    const img = doc?.images[0];
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

test("a CBZ upload becomes a right-to-left image book with ordered pages", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);

  const book = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(book.format).toBe("cbz");
  expect(book.epub_title).toBe("月台小提琴手 第1話");
  expect(book.epub_authors).toEqual(["周霜"]);
  expect(book.epub_series).toBe("月台小提琴手");
  expect(book.is_image_book).toBe(true);
  expect(book.cover_path).not.toBeNull();

  const pages = await (
    await page.request.get(`/api/books/${bookId}/pages`)
  ).json();
  expect(pages.layout).toBe("pre-paginated");
  expect(pages.direction).toBe("rtl");
  expect(pages.pages).toHaveLength(6);
  expect(pages.pages.map((p: { image: string }) => p.image)).toEqual(
    [1, 2, 3, 4, 5, 6].map((i) => `OEBPS/images/${String(i).padStart(4, "0")}.jpg`),
  );
  expect([pages.pages[3].width, pages.pages[3].height]).toEqual([1600, 1200]);

  const image = await page.request.get(
    `/api/books/${bookId}/content/${pages.pages[0].image}`,
  );
  expect(image.headers()["content-type"]).toBe("image/jpeg");

  const original = await page.request.get(`/api/books/${bookId}/original`);
  expect(original.headers()["content-disposition"]).toContain("attachment");
  expect((await original.body()).subarray(0, 2).toString()).toBe("PK");
});

test("the current reader opens the packed comic on its first page", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await page.addInitScript(() =>
    localStorage.setItem("reader-gestures-seen", "1"),
  );
  await page.goto(`/books/${bookId}/read`);
  await expect.poll(() => currentReaderImageLoaded(page), {
    timeout: 30_000,
  }).toBe(true);
});

test("the detail page offers the original CBZ", async ({ page }) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await page.goto(`/books/${bookId}`);
  await expect(
    page.getByRole("button", { name: "Imported from CBZ" }),
  ).toBeVisible();

  await page.getByTitle("More actions").click();
  const downloadEvent = page.waitForEvent("download");
  await page
    .getByRole("menuitem", { name: "Download original CBZ" })
    .click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toMatch(/\.cbz$/);
});
