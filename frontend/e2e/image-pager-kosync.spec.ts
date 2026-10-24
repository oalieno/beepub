import crypto from "node:crypto";
import { test, expect, type APIRequestContext } from "@playwright/test";
import { ADMIN, ADMIN_STATE } from "./helpers";
import {
  KITE_BOOK,
  openComic,
  pagerState,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * An e-reader's position bridged from kosync into a comic: the image
 * pager takes it as the text reader does — adopted outright when the book
 * was never read here, offered when it was. A page is one spine item, so
 * the device's chapter hint (DocFragment[N] of its xpointer) is the page
 * it lands on; the percentage is only the fallback. The book is eight
 * portrait pages read left to right, packed into a pre-paginated EPUB.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(90_000);

/** KOReader's partial md5 (services/partial_md5.py on the server): 1 KiB
 *  samples at 1024 << 2i for i = -1..10, the i = -1 step wrapping to 0. */
function partialMd5(buf: Buffer): string {
  const hash = crypto.createHash("md5");
  for (let i = -1; i <= 10; i++) {
    const offset = Number((1024n << BigInt((2 * i) & 31)) & 0xffffffffn);
    if (offset >= buf.length) break;
    hash.update(buf.subarray(offset, offset + 1024));
  }
  return hash.digest("hex");
}

/** The kosync document of a book: the digest of the EPUB the server keeps
 *  (for a CBZ, the one it packed at ingest). */
async function documentOf(request: APIRequestContext, bookId: string) {
  const res = await request.get(`/api/books/${bookId}/file`);
  expect(res.ok()).toBeTruthy();
  return partialMd5(await res.body());
}

/** Push a position as an e-reader would: the stock plugin's key is
 *  md5(password), and its device id is not the web's. */
async function pushFromDevice(
  request: APIRequestContext,
  document: string,
  page: number,
  percentage: number,
) {
  const res = await request.put("/kosync/syncs/progress", {
    headers: {
      "x-auth-user": ADMIN.username,
      "x-auth-key": crypto
        .createHash("md5")
        .update(ADMIN.password)
        .digest("hex"),
    },
    data: {
      document,
      progress: `/body/DocFragment[${page + 1}]/body/div/img`,
      percentage,
      device: "Kite E-Reader",
      device_id: "e2e-kite-ereader",
    },
  });
  expect(res.ok()).toBeTruthy();
}

async function marker(request: APIRequestContext, bookId: string) {
  return (await (await request.get(`/api/books/${bookId}/progress`)).json())
    .kosync;
}

test("a comic read here offers the e-reader's newer page and jumps to it", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, KITE_BOOK);
  const document = await documentOf(request, bookId);
  // Read here on the first page; the device then reads on to page six.
  // Its percentage points at page five: the chapter hint wins.
  await resetProgress(request, bookId);
  await pushFromDevice(request, document, 5, 0.6);
  expect((await marker(request, bookId))?.section_index).toBe(5);

  await openComic(page, bookId);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Kite E-Reader is at 60%; you are at 0%.");
  expect((await pagerState(page)).page).toBe(0);
  await dialog.getByRole("button", { name: "Jump" }).click();
  await expect.poll(async () => (await pagerState(page)).page).toBe(5);

  // The jump is saved: the marker is gone, the next open stays put.
  await expect.poll(() => marker(request, bookId)).toBeNull();
  await openComic(page, bookId);
  await page.waitForTimeout(1000);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect((await pagerState(page)).page).toBe(5);
});

test("a comic never read here opens on the e-reader's page", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, KITE_BOOK);
  const document = await documentOf(request, bookId);
  await resetProgress(request, bookId);
  // Its percentage alone would restore page four; the hint says seven.
  await pushFromDevice(request, document, 6, 0.4);
  // Progress rows outlive a run, so "never read here" is the saved
  // position without its CFI, as the server sends it for such a book.
  await page.route(`**/api/books/${bookId}/progress`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, cfi: null } });
  });

  await openComic(page, bookId);
  await expect.poll(async () => (await pagerState(page)).page).toBe(6);
  await expect(
    page.getByText("Jumped to your Kite E-Reader position (40%)"),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect.poll(() => marker(request, bookId)).toBeNull();
});
