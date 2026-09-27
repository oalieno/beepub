import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  PAGE_MARKERS_BOOK,
  iphone,
  marks,
  seedFixture,
  seedGesturesSeen,
} from "./ng-helpers";

/**
 * Positions written by other readers, in shapes our own reader never
 * produces — they must still open, not hang on the spinner:
 * - a saved position sitting on an empty print page marker
 *   (`<a id="page_43"/>`, a pagebreak span), which epub.js-era readers
 *   stored and then hung restoring;
 * - an Apple Books-style range CFI, where the text-node step lives in the
 *   shared path and the endpoints are bare offsets (`/4/8/1,:4,:17`)
 *   instead of our `/4/8,/1:4,/1:17`.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });

/** Chapter two, spine position 2. */
const CH2 = "/6/4!";

async function openAt(page: Page, url: string) {
  await seedGesturesSeen(page);
  const t0 = Date.now();
  await page.goto(url);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 15_000 },
  );
  return Date.now() - t0;
}

function where(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    return {
      index: core.lastLocation.index as number,
      text: doc.body?.textContent ?? "",
    };
  });
}

for (const [label, cfi] of [
  ["an inline page anchor", `epubcfi(${CH2}/4/4/2[page_43])`],
  ["a pagebreak span", `epubcfi(${CH2}/4/6[page_44])`],
]) {
  test(`a saved position on ${label} restores`, async ({ page }) => {
    const bookId = await seedFixture(page.request, PAGE_MARKERS_BOOK);
    const res = await page.request.put(`/api/books/${bookId}/progress`, {
      data: { cfi, percentage: 60, section_index: 1 },
    });
    expect(res.ok()).toBeTruthy();

    const ms = await openAt(page, `/books/${bookId}/read`);
    expect(ms).toBeLessThan(10_000);
    await expect.poll(async () => (await where(page)).index).toBe(1);
    expect((await where(page)).text).toContain("typesetter");
    // It opened on the book, not the load-failure screen.
    await expect(page.getByTestId("ng-chrome")).toHaveCount(1);
  });
}

test("an Apple Books-style range CFI jumps and draws", async ({ page }) => {
  const bookId = await seedFixture(page.request, PAGE_MARKERS_BOOK);
  await page.request.put(`/api/books/${bookId}/progress`, {
    data: {
      cfi: "epubcfi(/6/2!/4/2/1:0)",
      percentage: 0,
      section_index: 0,
    },
  });
  const cfi = `epubcfi(${CH2}/4/8/1,:4,:17)`;
  // A fresh row each run: the reader rewrites it to our own shape (below),
  // so last run's row no longer carries this CFI.
  const url = `/api/books/${bookId}/highlights`;
  for (const h of await (await page.request.get(url)).json()) {
    if (h.text === "quartermaster")
      expect((await page.request.delete(`${url}/${h.id}`)).ok()).toBeTruthy();
  }
  const created = await page.request.post(url, {
    data: { cfi_range: cfi, text: "quartermaster", color: "yellow" },
  });
  expect(created.ok()).toBeTruthy();
  const row = await created.json();

  // The jump every highlight list uses.
  const ms = await openAt(
    page,
    `/books/${bookId}/read?cfi=${encodeURIComponent(cfi)}`,
  );
  expect(ms).toBeLessThan(10_000);
  await expect.poll(async () => (await where(page)).index).toBe(1);

  // It anchors the word it names…
  const anchored = await page.evaluate((cfi) => {
    const core = window.__beepubReaderNG.core;
    const target = core.resolve(cfi);
    return String(target.anchor(core.getContents()[0].doc));
  }, cfi);
  expect(anchored).toBe("quartermaster");
  // …and the saved highlight is drawn there.
  await expect.poll(async () => (await marks(page)).length).toBe(1);
  // Healing stores it back in the shape our readers write.
  await expect
    .poll(async () => {
      const rows = await (await page.request.get(url)).json();
      return rows.find((h: { id: string }) => h.id === row.id)?.cfi_range;
    })
    .toBe(`epubcfi(${CH2}/4/8,/1:4,/1:17)`);
});
