import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  VERTICAL_PLATE_BOOK,
  iphone,
  openBook,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * reader-ng: an illustration set in vertical text — alone in its
 * paragraph, the way light novels carry their plates. It takes the full
 * width of its page and sits in the middle of it, rather than a margin
 * short, flush right, with a line of text squeezed in beside it.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });
test.setTimeout(90_000);

/** The plate's box and the page's, in viewport coordinates. */
function plate(page: Page) {
  return page.evaluate(() => {
    const { doc } = window.__beepubReaderNG.core.getContents()[0];
    const img = doc.querySelector("img")!;
    const r = img.getBoundingClientRect();
    const frame = doc.defaultView!.frameElement!.getBoundingClientRect();
    const host = window.__beepubReaderNG.paginator.getBoundingClientRect();
    return {
      img: { x: r.x + frame.x, y: r.y + frame.y, w: r.width, h: r.height },
      host: { x: host.x, y: host.y, w: host.width, h: host.height },
    };
  });
}

test("an illustration in vertical text fills its page's width and is centred on it", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, VERTICAL_PLATE_BOOK);
  await resetProgress(page.request, bookId);
  await openBook(page, bookId, { size: "24" }, VERTICAL_PLATE_BOOK);
  await page.evaluate(async () => {
    const core = window.__beepubReaderNG.core;
    const { doc } = core.getContents()[0];
    const range = doc.createRange();
    range.selectNode(doc.querySelector("img")!);
    await core.goTo(core.cfiOf(0, range));
  });
  await page.waitForTimeout(800);

  const { img, host } = await plate(page);
  // mx=24 (openBook): the page is the host less the two side gutters.
  expect(img.w).toBeCloseTo(host.w - 48, 0);
  const centre = { x: img.x + img.w / 2, y: img.y + img.h / 2 };
  expect(Math.abs(centre.x - (host.x + host.w / 2))).toBeLessThanOrEqual(1);
  expect(Math.abs(centre.y - (host.y + host.h / 2))).toBeLessThanOrEqual(1);
  // Whole on the page, top to bottom.
  expect(img.y).toBeGreaterThanOrEqual(host.y);
  expect(img.y + img.h).toBeLessThanOrEqual(host.y + host.h);

  // The text goes on after it: the next page is prose again.
  await page.evaluate(() => window.__beepubReaderNG.core.next());
  await page.waitForTimeout(500);
  const text = await page.evaluate(() =>
    window.__beepubReaderNG.core.lastLocation.range.toString(),
  );
  expect(text).toContain("風車之章第7段");
});
