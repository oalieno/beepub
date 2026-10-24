import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  CBZ_BOOK,
  openComic,
  pagerState,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * CBZ upload: the archive is packed into a pre-paginated EPUB at ingest
 * (one fixed-layout page per image, right-to-left when ComicInfo says so),
 * classified an image book on the spot, and its pages are served in
 * reading order for the pager. The reader hands it to the image pager;
 * the detail page offers the original.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

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
    [1, 2, 3, 4, 5, 6].map(
      (i) => `OEBPS/images/${String(i).padStart(4, "0")}.jpg`,
    ),
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

test("the reader opens the packed comic on its first page, a picture", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await resetProgress(page.request, bookId);
  await openComic(page, bookId);
  expect((await pagerState(page)).page).toBe(0);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const img = document.querySelector<HTMLImageElement>(
          '[data-testid="image-pager"] img',
        );
        return !!img && img.complete && img.naturalWidth > 0;
      }),
    )
    .toBe(true);
});

test("the detail page offers the original CBZ", async ({ page }) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await page.goto(`/books/${bookId}`);
  await expect(
    page.getByRole("button", { name: "Imported from CBZ" }),
  ).toBeVisible();

  await page.getByTitle("More actions").click();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Download original CBZ" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toMatch(/\.cbz$/);
});
