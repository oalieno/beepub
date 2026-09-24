import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  CBZ_BOOK,
  openComic,
  pagerState,
  seedFixture,
  setPagerSetting,
  stepPagerSetting,
  touchTap,
} from "./ng-helpers";

/**
 * The image pager: a pre-paginated book (here a comic packed from a CBZ:
 * six pages, right-to-left, page four a two-page spread) is claimed from
 * BookReader before it renders and drawn as images. Wide screens pair
 * portrait pages; the cover and the wide page stand alone. Position is
 * the page, saved as a CFI the legacy reader restores from too.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

const chrome = (page: Page) => page.getByTestId("ng-chrome");
const viewerClose = (page: Page) =>
  page.getByRole("button", { name: "Close", exact: true });

/** The settings button sits in the bottom bar, which a tap in the
 *  middle of the page brings up on a phone. */
async function showBottomBar(page: Page) {
  const settings = page.getByRole("button", { name: "Reader settings" });
  if (await settings.isVisible()) return;
  const b = (await page.getByTestId("image-pager").boundingBox())!;
  await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
  await expect(settings).toBeVisible();
}

async function settleSave(page: Page) {
  // The pager debounces its save by two seconds after a move.
  await page.waitForTimeout(2600);
}

test("double page: cover alone, then pairs, the spread alone", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await openComic(page, bookId);
  // Start from the cover whatever an earlier run left behind.
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));
  let state = await pagerState(page);
  expect(state.mode).toBe("single");
  expect(state.shown).toEqual([0]);
  await setPagerSetting(page, "setting-pager-mode", "Double page");

  state = await pagerState(page);
  expect(state.total).toBe(6);
  expect(state.twoPage).toBe(true);
  expect(state.rtl).toBe(true);
  expect(state.shown).toEqual([0]);
  await expect(chrome(page)).toContainText("1 / 6");
  expect(state.cfi).toMatch(/^epubcfi\(\/6\/2(\[[^\]]*\])?!\/4\)$/);

  // Pages 2+3 pair; right-to-left puts page 2 on the right.
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  state = await pagerState(page);
  expect(state.shown).toEqual([2, 1]);
  await expect(chrome(page)).toContainText("2–3 / 6");
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.pager.loaded))
    .toBe(true);
  const images = page.locator('[data-testid="image-pager"] img');
  await expect(images).toHaveCount(2);
  for (const img of await images.all()) {
    expect(
      await img.evaluate((el: HTMLImageElement) => el.naturalWidth),
    ).toBeGreaterThan(0);
  }

  // The wide page (4) stands alone, then 5+6 pair.
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  expect((await pagerState(page)).shown).toEqual([3]);
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  expect((await pagerState(page)).shown).toEqual([5, 4]);
  await expect(chrome(page)).toContainText("5–6 / 6");

  // Past the last page: the book-end overlay, no move.
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  await expect(page.getByTestId("book-end")).toBeVisible();
  expect((await pagerState(page)).page).toBe(4);
  await page.keyboard.press("Escape");

  // Forcing the direction flips the pair on screen.
  await setPagerSetting(page, "setting-pager-direction", "Left to right");
  state = await pagerState(page);
  expect(state.rtl).toBe(false);
  expect(state.shown).toEqual([4, 5]);
  await setPagerSetting(page, "setting-pager-direction", "Auto");

  // Shifted pairing: the first page joins the second, so 1+2, 3 alone
  // before the wide page, 4, then 5+6 — and it is remembered per book.
  await setPagerSetting(page, "setting-pager-shift", "From page 1");
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));
  state = await pagerState(page);
  expect(state.shift).toBe(true);
  expect(state.shown).toEqual([1, 0]);
  await expect(chrome(page)).toContainText("1–2 / 6");
  await page.evaluate(() => window.__beepubReaderNG.pager.next());
  expect((await pagerState(page)).shown).toEqual([2]);
  await page.reload();
  await openComic(page, bookId);
  expect((await pagerState(page)).shift).toBe(true);
  // The reload restored page 3; unshifted it pairs with page 2 again.
  await setPagerSetting(page, "setting-pager-shift", "Cover alone");
  expect((await pagerState(page)).shown).toEqual([2, 1]);
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));
  expect((await pagerState(page)).shown).toEqual([0]);

  // Padding shrinks the picture inside the same box.
  const img = page.locator('[data-testid="image-pager"] img').first();
  const before = (await img.boundingBox())!;
  await stepPagerSetting(page, "Page padding", "up", 3);
  expect((await pagerState(page)).padding).toBe(24);
  const after = (await img.boundingBox())!;
  expect(after.height).toBeLessThan(before.height - 40);
  await stepPagerSetting(page, "Page padding", "down", 3);
  expect((await pagerState(page)).padding).toBe(0);

  await setPagerSetting(page, "setting-pager-mode", "Single page");
  expect((await pagerState(page)).shown).toEqual([0]);
});

test("the page is the position: it restores here and in the legacy reader", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await openComic(page, bookId);
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(3));
  await settleSave(page);

  const saved = await (
    await page.request.get(`/api/books/${bookId}/progress`)
  ).json();
  expect(saved.cfi).toMatch(/^epubcfi\(\/6\/8(\[[^\]]*\])?!\/4\)$/);
  expect(saved.percentage).toBe(60);
  expect(saved.current_page).toBe(4);
  expect(saved.total_pages).toBe(6);

  await openComic(page, bookId);
  expect((await pagerState(page)).page).toBe(3);

  // The legacy reader reads the same CFI as spine item four.
  await page.goto(`/books/${bookId}/read-legacy`);
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
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as any).__beepubReader.rendition.currentLocation().start
            .index,
      ),
    )
    .toBe(3);
});

test("the continuous modes stack the pages and follow the scroll", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CBZ_BOOK);
  await openComic(page, bookId);
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));
  const scroller = page.locator('[data-testid="image-pager"] > div');

  await setPagerSetting(page, "setting-pager-mode", "Continuous vertical");
  await expect(page.getByTestId("image-pager")).toHaveAttribute(
    "data-flow",
    "vertical",
  );
  expect((await pagerState(page)).twoPage).toBe(false);
  await scroller.evaluate((el) => (el.scrollTop = el.scrollHeight));
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(5);
  await expect(chrome(page)).toContainText("6 / 6");
  // No scrollbar: the strip fills the pager edge to edge.
  expect(
    await scroller.evaluate((el) => el.clientWidth === el.offsetWidth),
  ).toBe(true);

  // A mouse drags the strip: pulling up from the top scrolls down, and
  // a drag is not a chrome tap.
  await scroller.evaluate((el) => (el.scrollTop = 0));
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(0);
  const box = (await scroller.boundingBox())!;
  const chromeShown = await chrome(page).isVisible();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.8);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.2, {
    steps: 8,
  });
  await page.mouse.up();
  const released = await scroller.evaluate((el) => el.scrollTop);
  expect(released).toBeGreaterThan(box.height * 0.5);
  expect(await chrome(page).isVisible()).toBe(chromeShown);
  // A quick release flings: the strip keeps going after the hand lets go.
  await expect
    .poll(() => scroller.evaluate((el) => el.scrollTop))
    .toBeGreaterThan(released + 50);
  await scroller.evaluate((el) => (el.scrollTop = el.scrollHeight));
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(5);

  // Webtoon: the same strip edge to edge; the position carries over.
  await setPagerSetting(page, "setting-pager-mode", "Webtoon");
  await expect(page.getByTestId("image-pager")).toHaveAttribute(
    "data-flow",
    "webtoon",
  );
  expect((await pagerState(page)).page).toBe(5);
  await scroller.evaluate((el) => (el.scrollTop = 0));
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(0);

  // Horizontal: a right-to-left book starts at the right end and the
  // strip runs leftward. Switching between strips keeps the page (the
  // relayout's own scroll event must not read the new origin as page 1).
  await scroller.evaluate((el) => {
    const target = el.querySelector<HTMLElement>('[data-page="3"]')!;
    el.scrollTop = target.offsetTop + target.offsetHeight / 3;
  });
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(3);
  await setPagerSetting(page, "setting-pager-mode", "Continuous horizontal");
  await expect(page.getByTestId("image-pager")).toHaveAttribute(
    "data-flow",
    "horizontal",
  );
  await expect(scroller).toHaveCSS("direction", "rtl");
  await page.waitForTimeout(800);
  expect((await pagerState(page)).page).toBe(3);
  // Back to a vertical strip: every page box is exactly its picture (a
  // WebKit relayout bug left the horizontal strip's height on the box).
  await setPagerSetting(page, "setting-pager-mode", "Continuous vertical");
  await page.waitForTimeout(800);
  expect(
    await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="image-pager"] [data-page]')]
        .filter((el) => el.querySelector("img"))
        .every(
          (el) =>
            Math.abs(
              el.getBoundingClientRect().height -
                el.querySelector("img")!.getBoundingClientRect().height,
            ) < 1,
        ),
    ),
  ).toBe(true);
  await setPagerSetting(page, "setting-pager-mode", "Continuous horizontal");
  await page.waitForTimeout(800);
  await scroller.evaluate((el) => (el.scrollLeft = -el.scrollWidth));
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(5);
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(4);
  // A plain wheel moves the strip: down runs forward (leftward here),
  // up runs back.
  await scroller.evaluate((el) => (el.scrollLeft = 0));
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(0);
  const hbox = (await scroller.boundingBox())!;
  await page.mouse.move(hbox.x + hbox.width / 2, hbox.y + hbox.height / 2);
  await page.mouse.wheel(0, 2000);
  await expect
    .poll(() => scroller.evaluate((el) => el.scrollLeft))
    .toBeLessThan(-1000);
  await page.mouse.wheel(0, -4000);
  await expect.poll(() => scroller.evaluate((el) => el.scrollLeft)).toBe(0);

  // Back to pages for the specs that follow; the choice is remembered.
  await setPagerSetting(page, "setting-pager-mode", "Single page");
  await expect(page.getByTestId("image-pager")).toHaveAttribute(
    "data-flow",
    "paged",
  );
  expect((await pagerState(page)).page).toBe(0);
});

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test("single pages; the left tap zone turns forward in a right-to-left book", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, CBZ_BOOK);
    await openComic(page, bookId);
    await page.evaluate(() => window.__beepubReaderNG.pager.goTo(1));
    let state = await pagerState(page);
    expect(state.twoPage).toBe(false);
    expect(state.shown).toEqual([1]);

    const pager = page.getByTestId("image-pager");
    const box = (await pager.boundingBox())!;
    // Left quarter: forward (the next page sits to the left in manga).
    await page.mouse.click(box.x + box.width * 0.1, box.y + box.height / 2);
    expect((await pagerState(page)).page).toBe(2);
    // Right quarter: back.
    await page.mouse.click(box.x + box.width * 0.9, box.y + box.height / 2);
    expect((await pagerState(page)).page).toBe(1);
    // Arrow keys follow the screen, not the reading order.
    await page.keyboard.press("ArrowLeft");
    expect((await pagerState(page)).page).toBe(2);
    await page.keyboard.press("ArrowRight");
    expect((await pagerState(page)).page).toBe(1);

    // A double tap zooms in and a page turn resets it.
    await page.mouse.dblclick(box.x + box.width / 2, box.y + box.height / 2);
    state = await pagerState(page);
    expect(state.scale).toBeGreaterThan(1);
    expect(state.page).toBe(1);
    await page.keyboard.press("ArrowLeft");
    state = await pagerState(page);
    expect(state.scale).toBe(1);
    expect(state.page).toBe(2);
  });

  test("a long press on a page opens it in the viewer, paged and in the strip", async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, CBZ_BOOK);
    await openComic(page, bookId);
    await page.evaluate(() => window.__beepubReaderNG.pager.goTo(1));
    const pager = page.getByTestId("image-pager");
    // The system image menu (Save to Photos…) must not claim the press.
    // (Chromium has no such property, so read the declaration itself.)
    expect(await pager.getAttribute("style")).toContain(
      "-webkit-touch-callout: none",
    );

    const cdp = await context.newCDPSession(page);
    const centre = async () => {
      const img = page
        .locator('[data-testid="image-pager"] img:visible')
        .first();
      const b = (await img.boundingBox())!;
      return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
    };

    // Paged: the hold opens the page; its release is not a tap or a turn.
    const barShown = await page
      .getByRole("button", { name: "Reader settings" })
      .isVisible();
    await touchTap(cdp, await centre(), 700);
    await expect(viewerClose(page)).toBeVisible();
    await page.waitForTimeout(400);
    expect((await pagerState(page)).page).toBe(1);
    expect(
      await page.getByRole("button", { name: "Reader settings" }).isVisible(),
    ).toBe(barShown);
    // Keys belong to the viewer while it is open.
    await page.keyboard.press("ArrowLeft");
    expect((await pagerState(page)).page).toBe(1);
    await page.keyboard.press("Escape");
    await expect(viewerClose(page)).toHaveCount(0);

    // The continuous strip answers the same press.
    await showBottomBar(page);
    await setPagerSetting(page, "setting-pager-mode", "Continuous vertical");
    await expect(pager).toHaveAttribute("data-flow", "vertical");
    // The middle of the screen: the first picture may sit above it.
    const box = (await pager.boundingBox())!;
    const mid = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    expect(
      await page.evaluate(
        ({ x, y }) => document.elementFromPoint(x, y)?.tagName,
        mid,
      ),
    ).toBe("IMG");
    await touchTap(cdp, mid, 700);
    await expect(viewerClose(page)).toBeVisible();
    await viewerClose(page).click();
    await expect(viewerClose(page)).toHaveCount(0);
    await showBottomBar(page);
    await setPagerSetting(page, "setting-pager-mode", "Single page");
  });
});
