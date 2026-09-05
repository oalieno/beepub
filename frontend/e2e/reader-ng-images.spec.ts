import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  PLATES_BOOK,
  iphone,
  location,
  openBook,
  seedFixture,
  touchTap,
} from "./ng-helpers";

/**
 * reader-ng: the book's own pictures. The images of the sections ahead
 * are fetched while the current one is being read, so a turn into a
 * chapter that opens on a plate does not wait for the plate (the cache
 * is a window around the current section — what falls out of it is
 * fetched again); and a long press on a picture opens it full-screen,
 * on touch and with the mouse alike.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

function countPlates(page: Page) {
  const counts: Record<string, number> = {};
  page.on("request", (r) => {
    const m = /\/content\/OEBPS\/images\/(plate\d)\.png$/.exec(
      new URL(r.url()).pathname,
    );
    if (m) counts[m[1]] = (counts[m[1]] ?? 0) + 1;
  });
  return counts;
}

function sectionIndex(page: Page) {
  return page.evaluate(
    () => window.__beepubReaderNG.core.lastLocation.index as number,
  );
}

async function goTo(page: Page, index: number) {
  await page.evaluate((i) => window.__beepubReaderNG.core.goTo(i), index);
  await expect.poll(() => sectionIndex(page)).toBe(index);
  // Let the prefetch pass for the new position settle.
  await page.waitForTimeout(600);
}

/** The plate <img> (or SVG <image>) of the section on screen decoded. */
function plateDecoded(page: Page) {
  return page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const img = doc.querySelector("img");
    if (img) return img.complete && img.naturalWidth > 0;
    // The parser rewrites the SVG image's reference to its blob URL (the
    // attribute may stay namespaced in the XML document).
    const svgImage = doc.querySelector("image");
    const href =
      svgImage?.getAttribute("href") ??
      svgImage?.getAttributeNS("http://www.w3.org/1999/xlink", "href");
    return !!href?.startsWith("blob:");
  });
}

test("the plates of the next three chapters are fetched ahead and served from memory on the turn", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, PLATES_BOOK);
  const counts = countPlates(page);
  await openBook(page, bookId, {}, PLATES_BOOK);

  // Still on chapter 1, the three plates ahead have been fetched once.
  await expect
    .poll(() => ({ ...counts }), { timeout: 10_000 })
    .toEqual({ plate2: 1, plate3: 1, plate4: 1 });
  expect(await sectionIndex(page)).toBe(0);

  // Turning into chapter 2 shows its plate without a second request; the
  // SVG <image> in chapter 3 likewise.
  await goTo(page, 1);
  await expect.poll(() => plateDecoded(page)).toBe(true);
  await goTo(page, 2);
  await expect.poll(() => plateDecoded(page)).toBe(true);
  expect(counts).toEqual({ plate2: 1, plate3: 1, plate4: 1 });

  // From chapter 4 the window is {4, 3}: chapter 2's plate is dropped and
  // fetched again when the reader comes back to it.
  await goTo(page, 3);
  expect(counts.plate4).toBe(1);
  await goTo(page, 1);
  await expect.poll(() => plateDecoded(page)).toBe(true);
  expect(counts.plate2).toBe(2);
});

/** Viewport point at the centre of the plate on screen. */
function platePoint(page: Page) {
  return page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const el = doc.querySelector("img, svg") as Element | null;
    if (!el) return null;
    const frame = (
      doc.defaultView!.frameElement as HTMLIFrameElement
    ).getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return {
      x: frame.left + r.left + r.width / 2,
      y: frame.top + r.top + r.height / 2,
    };
  });
}

const viewerClose = (page: Page) =>
  page.getByRole("button", { name: "Close", exact: true });

test("a long press with the mouse opens the picture full-screen; a click does not", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, PLATES_BOOK);
  await openBook(page, bookId, {}, PLATES_BOOK);
  await goTo(page, 1);
  const pt = (await platePoint(page))!;

  // A plain click on the picture is a tap like any other (here: the
  // middle of the page, the chrome toggle) — no viewer.
  await page.mouse.click(pt.x, pt.y);
  await page.waitForTimeout(300);
  await expect(viewerClose(page)).toHaveCount(0);

  await page.mouse.move(pt.x, pt.y);
  await page.mouse.down();
  await page.waitForTimeout(700);
  await page.mouse.up();
  await expect(viewerClose(page)).toBeVisible();
  await expect(page.locator('img[src^="blob:"]:visible').last()).toBeVisible();
  // The release did not turn the page under the viewer.
  expect((await location(page)).index).toBe(1);

  await page.keyboard.press("Escape");
  await expect(viewerClose(page)).toHaveCount(0);
});

test.describe("phone", () => {
  test.use({ ...iphone });

  test("a long press on a picture opens it, and the release turns no page", async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, PLATES_BOOK);
    await openBook(page, bookId, {}, PLATES_BOOK);
    await goTo(page, 1);
    const pt = (await platePoint(page))!;
    const cdp = await context.newCDPSession(page);
    await touchTap(cdp, pt, 700);
    await expect(viewerClose(page)).toBeVisible();
    await page.waitForTimeout(400);
    expect((await location(page)).index).toBe(1);
    await viewerClose(page).click();
    await expect(viewerClose(page)).toHaveCount(0);
  });
});
