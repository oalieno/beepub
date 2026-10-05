import { test, expect, type CDPSession, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  TOUCH_BOOK,
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
 * reader-ng page-turn modes on device-shaped input. Two modes: a fast
 * fade (the default) and a slide in which one page moves over the other
 * (its own spec: reader-ng-slide.spec.ts). Here: the fade, the stored
 * choice, and that every turn follows the book's declared page
 * progression even on a horizontal illustration plate inside a
 * vertical-rl book.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });
test.setTimeout(60_000);

/** Record every opacity animation the reader starts on the page (the
 *  fade of a page turn) from here on. */
function watchFades(page: Page) {
  return page.evaluate(() => {
    const paginator = window.__beepubReaderNG.paginator as HTMLElement;
    const animate = paginator.animate.bind(paginator);
    window.__fades = [];
    paginator.animate = (keyframes, options) => {
      const frames = keyframes as Keyframe[];
      window.__fades!.push(Number(frames[frames.length - 1]!.opacity));
      return animate(keyframes, options);
    };
  });
}

function fades(page: Page): Promise<number[]> {
  return page.evaluate(() => window.__fades ?? []);
}

/** Whether the page is fully visible with no fade left running. */
function pageOpaque(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const paginator = window.__beepubReaderNG.paginator as HTMLElement;
    return (
      getComputedStyle(paginator).opacity === "1" &&
      paginator.getAnimations().length === 0
    );
  });
}

/** The page on screen, counted within its section. */
function pageNumber(page: Page): Promise<number> {
  return page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return l.size ? Math.round(l.fraction / l.size) : 0;
  });
}

function turnMode(page: Page) {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    return {
      set: core.pageTurn as string,
      effective: core.effectivePageTurn() as string,
      // The slide's second rendering of the neighbouring page: built for
      // that mode only.
      ghost: !!core.ghost,
      // The old finger-follow push is gone from every mode.
      pushes: paginator.hasAttribute("animated") as boolean,
    };
  });
}

async function openSettings(page: Page, cdp: CDPSession) {
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  const bar = page.getByRole("toolbar", { name: "Reading controls" });
  await expect(bar).toBeVisible();
  await bar.getByRole("button", { name: "Reader settings" }).click();
  await expect(page.getByText("Line spacing")).toBeVisible();
}

test("a page turn fades by default: it lands on the next page, fully visible", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId, { turn: "" });
  expect(await turnMode(page)).toEqual({
    set: "fade",
    effective: "fade",
    ghost: false,
    pushes: false,
  });
  await watchFades(page);

  await page.keyboard.press("ArrowRight");
  await expect.poll(() => pageNumber(page)).toBe(1);
  expect((await location(page)).reason).toBe("page");
  await expect.poll(() => pageOpaque(page)).toBe(true);
  // Out, then in.
  expect(await fades(page)).toEqual([0, 1]);

  // Navigation is not a page turn: no fade. (The paginator drops
  // navigation for ~100ms after a page turn; let it settle.)
  await page.waitForTimeout(300);
  await page.evaluate(() => {
    window.__fades = [];
    void window.__beepubReaderNG.core.goTo(0);
  });
  await expect.poll(() => pageNumber(page)).toBe(0);
  expect(await fades(page)).toEqual([]);
  expect(await pageOpaque(page)).toBe(true);
});

test("fading turns keep up with quick paging and never pile up", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId, { turn: "fade" });
  const pages = (await page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return l.size ? Math.round(1 / l.size) : 1;
  })) as number;
  expect(pages).toBeGreaterThan(8);

  // Five turns just over the paginator's 100ms lock apart — each one
  // asked for while the fade of the one before is still on screen.
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const core = window.__beepubReaderNG.core;
        let left = 5;
        const step = () => {
          core.next();
          if (--left) setTimeout(step, 110);
          else resolve();
        };
        step();
      }),
  );
  await expect.poll(() => pageNumber(page)).toBe(5);
  await expect.poll(() => pageOpaque(page)).toBe(true);

  // A burst inside the lock is one turn, as it is without the fade —
  // nothing is queued up behind it.
  await page.waitForTimeout(300);
  await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    core.next();
    core.next();
    core.next();
  });
  await expect.poll(() => pageNumber(page)).toBe(6);
  await page.waitForTimeout(500);
  expect(await pageNumber(page)).toBe(6);
  expect(await pageOpaque(page)).toBe(true);
});

test("a reader who asked for reduced motion gets bare page turns", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId, { turn: "fade" });
  await watchFades(page);
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => pageNumber(page)).toBe(1);
  expect(await fades(page)).toEqual([]);
  expect(await pageOpaque(page)).toBe(true);
});

test("modes stored before there were two are read as today's", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId);
  const cases = [
    { stored: "follow", mode: "slide" },
    { stored: "animated", mode: "slide" },
    { stored: "instant", mode: "fade" },
    { stored: "something-else", mode: "fade" },
  ];
  for (const { stored, mode } of cases) {
    await page.evaluate(
      (value) => localStorage.setItem("reader-page-turn", value),
      stored,
    );
    await openBook(page, bookId, { turn: "" });
    expect(await turnMode(page)).toEqual({
      set: mode,
      effective: mode,
      ghost: mode === "slide",
      pushes: false,
    });
    expect(
      await page.evaluate(() => localStorage.getItem("reader-page-turn")),
    ).toBe(mode);
  }
});

test("the settings sheet offers the two modes and stores the choice", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId, { turn: "" });
  const cdp = await context.newCDPSession(page);
  await openSettings(page, cdp);
  const row = page.getByTestId("setting-page-turn");
  await expect(row.getByRole("button")).toHaveText(["Fast fade", "Slide"]);

  await row.getByRole("button", { name: "Slide" }).click();
  await expect.poll(async () => (await turnMode(page)).effective).toBe("slide");
  expect(
    await page.evaluate(() => localStorage.getItem("reader-page-turn")),
  ).toBe("slide");

  await row.getByRole("button", { name: "Fast fade" }).click();
  await expect.poll(async () => (await turnMode(page)).effective).toBe("fade");
  expect(await turnMode(page)).toEqual({
    set: "fade",
    effective: "fade",
    ghost: false,
    pushes: false,
  });
  expect(
    await page.evaluate(() => localStorage.getItem("reader-page-turn")),
  ).toBe("fade");
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
