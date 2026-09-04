import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { openBook, resetProgress, seedBook } from "./ng-helpers";

/**
 * reader-ng ↔ current reader interop: the two readers share one progress
 * row per book, so a position saved by either must restore in the other.
 * read-ng writes the point CFI where the visible text starts (what the
 * current reader stores); the current reader's rows resolve on read-ng's
 * page grid.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

// The fixture is shared with the selection specs, which assume it opens
// on its first page: leave its progress there.
test.afterEach(async ({ page }) => {
  await resetProgress(page.request, await seedBook(page.request));
});

function progressPut(page: Page) {
  return page.waitForResponse(
    (r) => r.request().method() === "PUT" && r.url().endsWith("/progress"),
    { timeout: 10_000 },
  );
}

/** The current reader's location, once its manager exists. */
async function openCurrentReader(page: Page, bookId: string) {
  await page.evaluate(() => localStorage.setItem("reader-gestures-seen", "1"));
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
  // Let the restore's page correction settle.
  await page.waitForTimeout(1500);
  return page.evaluate(() => {
    const loc = (window as any).__beepubReader.rendition.currentLocation();
    return {
      cfi: loc.start.cfi as string,
      page: loc.start.displayed.page as number,
      total: loc.start.displayed.total as number,
    };
  });
}

test("a position saved by read-ng restores in the current reader, and back", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);

  // read-ng: read a few pages in; the debounced save lands.
  await openBook(page, bookId);
  const saved = progressPut(page);
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(250);
  }
  await saved;
  const ng = await page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return { cfi: l.startCfi as string, fraction: l.fraction as number };
  });
  expect(ng.fraction).toBeGreaterThan(0);
  const row = await (
    await page.request.get(`/api/books/${bookId}/progress`)
  ).json();
  // A point CFI, as the current reader stores it.
  expect(row.cfi).toBe(ng.cfi);
  expect(row.cfi).not.toContain(",");

  // Current reader: restores from that row past its first page. The two
  // readers' page grids differ (margins, gaps), so the page number is
  // not comparable — the anchor's paragraph is.
  const current = await openCurrentReader(page, bookId);
  expect(current.page).toBeGreaterThan(1);
  const paragraphOf = (cfi: string) => /\/4\/(\d+)/.exec(cfi)?.[1];
  expect(paragraphOf(current.cfi)).toBeTruthy();

  // Current reader: turn a page, let it save its own position.
  const saved2 = progressPut(page);
  await page.keyboard.press("ArrowRight");
  await saved2;
  const row2 = await (
    await page.request.get(`/api/books/${bookId}/progress`)
  ).json();
  expect(row2.cfi).not.toBe(row.cfi);

  // read-ng: restores from the current reader's row — the anchored
  // paragraph starts inside the visible page.
  await openBook(page, bookId, { restore: "1" });
  const landed = await page.evaluate((cfi) => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const range: Range = core.resolve(cfi).anchor(doc);
    const r = range.getBoundingClientRect();
    const frame = doc.defaultView!.frameElement as HTMLIFrameElement;
    const container = frame.parentElement!.parentElement!;
    const cb = container.getBoundingClientRect();
    const fb = frame.getBoundingClientRect();
    const x = fb.left + r.left;
    const y = fb.top + r.top;
    return (
      x >= cb.left - 1 &&
      x <= cb.right + 1 &&
      y >= cb.top - 1 &&
      y <= cb.bottom + 1
    );
  }, row2.cfi);
  expect(landed).toBe(true);
  expect(
    await page.evaluate(
      () => window.__beepubReaderNG.core.lastLocation.fraction as number,
    ),
  ).toBeGreaterThan(0);
});
