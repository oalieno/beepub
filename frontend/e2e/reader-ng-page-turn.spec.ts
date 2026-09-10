import { test, expect, type CDPSession, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  TOUCH_BOOK,
  VERTICAL_LONG_BOOK,
  VERTICAL_MIXED_BOOK,
  VERTICAL_MIXED_UNDECLARED_BOOK,
  RAINY_POST_OFFICE_BOOK,
  iphone,
  location,
  openBook,
  seedFixture,
  swipe,
  touchTap,
} from "./ng-helpers";

/**
 * reader-ng page-turn modes on device-shaped input (owner's device
 * feedback, 09-06): finger-follow must track the finger instead of
 * oscillating (gesture geometry in screen coordinates — the drag scrolls
 * the very frame the touch events come from), vertical text turns
 * instantly whatever the mode says (its pages are stacked vertically),
 * and every turn follows the book's declared page progression even on a
 * horizontal illustration plate inside a vertical-rl book.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });
test.setTimeout(60_000);

/** The paginator's scroll offset along its paging axis. */
function scrollOffset(page: Page): Promise<number> {
  return page.evaluate(() => window.__beepubReaderNG.paginator.start as number);
}

/** A slow horizontal drag in equal steps, sampling the scroll offset
 *  after each step; the finger lifts at the end. */
async function dragSampling(
  cdp: CDPSession,
  page: Page,
  from: { x: number; y: number },
  dx: number,
  steps: number,
): Promise<number[]> {
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: from.x, y: from.y }],
  });
  const samples: number[] = [];
  for (let i = 1; i <= steps; i++) {
    await new Promise((resolve) => setTimeout(resolve, 16));
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: from.x + (dx * i) / steps, y: from.y }],
    });
    samples.push(await scrollOffset(page));
  }
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  return samples;
}

test("finger-follow tracks the finger monotonically and snaps to the next page", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId, { turn: "follow" });
  const cdp = await context.newCDPSession(page);

  // Finger moving left pulls in the page on the right: the offset grows
  // with the finger and never runs back (a drag measured in the moving
  // frame's own coordinates fed each scroll back as a reverse move).
  // (The offset counts from the paginator's leading spacer page, so
  // only its growth is meaningful.)
  const samples = await dragSampling(cdp, page, { x: 320, y: 400 }, -200, 20);
  for (let i = 1; i < samples.length; i++) {
    expect(samples[i]).toBeGreaterThanOrEqual(samples[i - 1]!);
  }
  const travelled = samples[samples.length - 1]! - samples[0]!;
  expect(travelled).toBeGreaterThan(150);
  expect(travelled).toBeLessThanOrEqual(205);

  // Released past half a page, it settles on the next page.
  await expect
    .poll(async () => (await location(page)).fraction, { timeout: 3_000 })
    .toBeGreaterThan(0);
  expect((await location(page)).reason).toBe("snap");
});

test("vertical text ignores finger-follow and turns instantly, and the sheet says so", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, VERTICAL_LONG_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "follow", font: "sans" },
    VERTICAL_LONG_BOOK,
  );
  const before = await location(page);
  const pages = (await page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return l.size ? Math.round(1 / l.size) : 1;
  })) as number;
  test.skip(pages < 3, "vertical fragmentation degenerate — CJK fonts missing");
  const cdp = await context.newCDPSession(page);

  // Finger moving right (forward in a vertical-rl book): the page does
  // not creep along its vertical scroll axis under a horizontal drag…
  const samples = await dragSampling(cdp, page, { x: 100, y: 400 }, 160, 12);
  expect(new Set(samples).size).toBe(1);
  // …and the release is an ordinary threshold swipe: one page forward.
  await expect
    .poll(async () => (await location(page)).fraction, { timeout: 3_000 })
    .toBeGreaterThan(before.fraction);
  expect((await location(page)).index).toBe(before.index);

  // The settings sheet explains why the mode does not apply here.
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  const bar = page.getByRole("toolbar", { name: "Reading controls" });
  await expect(bar).toBeVisible();
  await bar.getByRole("button", { name: "Reader settings" }).click();
  await expect(
    page.getByText("Vertical books always turn instantly", { exact: false }),
  ).toBeVisible();
});

test("page turns follow the book's direction across a horizontal plate", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, VERTICAL_MIXED_BOOK);
  await openBook(page, bookId, { font: "sans" }, VERTICAL_MIXED_BOOK);
  const cdp = await context.newCDPSession(page);
  const goTo = (index: number) =>
    page.evaluate((i) => window.__beepubReaderNG.core.goTo(i), index);
  const index = async () => (await location(page)).index;

  // The plate between the chapters is horizontal-tb, yet the book
  // advances leftward: a rightward swipe on it is "next", as everywhere.
  await goTo(1);
  await expect.poll(index).toBe(1);
  await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
  await expect.poll(index).toBe(2);

  // And back over it: left = previous, right = next — no loop.
  await swipe(cdp, { x: 300, y: 400 }, { x: 80, y: 400 });
  await expect.poll(index).toBe(1);
  await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
  await expect.poll(index).toBe(2);

  // The same mapping the arrow keys and tap zones use. (The paginator
  // drops navigation for ~100ms after a page turn; let it settle.)
  await page.waitForTimeout(300);
  await goTo(1);
  await expect.poll(index).toBe(1);
  await page.evaluate(() => window.__beepubReaderNG.core.goLeft());
  await expect.poll(index).toBe(2);
  await goTo(1);
  await expect.poll(index).toBe(1);
  await page.evaluate(() => window.__beepubReaderNG.core.goRight());
  await expect.poll(index).toBe(0);
});

test("an undeclared book infers its direction from its vertical text and keeps it across the plate", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(
    page.request,
    VERTICAL_MIXED_UNDECLARED_BOOK,
  );
  await openBook(
    page,
    bookId,
    { font: "sans" },
    VERTICAL_MIXED_UNDECLARED_BOOK,
  );
  const cdp = await context.newCDPSession(page);
  const index = async () => (await location(page)).index;

  // Chapter one (vertical) has been on screen: the book reads leftward
  // for the rest of the session, plate included.
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
  await expect.poll(index).toBe(1);
  await page.waitForTimeout(300);
  await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
  await expect.poll(index).toBe(2);
  await swipe(cdp, { x: 300, y: 400 }, { x: 80, y: 400 });
  await expect.poll(index).toBe(1);
  await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
  await expect.poll(index).toBe(2);
});

test("an undeclared horizontal book with a class-gated vertical rule in its sheet reads rightward", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, RAINY_POST_OFFICE_BOOK);
  await openBook(page, bookId, { font: "sans" }, RAINY_POST_OFFICE_BOOK);
  const cdp = await context.newCDPSession(page);
  const index = async () => (await location(page)).index;
  expect(
    await page.evaluate(() => window.__beepubReaderNG.core.advancesLeftward()),
  ).toBe(false);
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
  await expect.poll(index).toBe(1);
  await page.waitForTimeout(300);
  // Swiping leftward (finger right to left) turns forward; the chapter
  // runs several pages, so the move shows as a fraction.
  const forward = async () => {
    const l = await location(page);
    return l.index > 1 || l.fraction > 0;
  };
  await swipe(cdp, { x: 300, y: 400 }, { x: 80, y: 400 });
  await expect.poll(forward).toBe(true);
  await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
  await expect.poll(forward).toBe(false);
  expect(await index()).toBe(1);
});

test("an undeclared book opened on its plate reads leftward from the first turn", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(
    page.request,
    VERTICAL_MIXED_UNDECLARED_BOOK,
  );
  // Straight onto the plate: no vertical section has rendered yet; the
  // stylesheet scan at load is what knows the book is vertical.
  await openBook(
    page,
    bookId,
    { font: "sans", cfi: "epubcfi(/6/4!/4/2)" },
    { ...VERTICAL_MIXED_UNDECLARED_BOOK, readyText: "卷二插畫" },
  );
  const cdp = await context.newCDPSession(page);
  const index = async () => (await location(page)).index;
  expect(await index()).toBe(1);
  await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
  await expect.poll(index).toBe(2);
});
