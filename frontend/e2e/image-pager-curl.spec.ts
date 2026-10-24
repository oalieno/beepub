import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  CURL_BOOK,
  openComic,
  pagerState,
  seedFixture,
  setPagerSetting,
} from "./ng-helpers";

/**
 * The curl page turn of the image pager: a sheet lifted by its corner and
 * folded over the spine (single and double page). The book is nine flat
 * colour pages read right to left — in double page the cover alone, then
 * four pairs. The position moves when the turn lands, not when it starts:
 * the chrome, the progress and the saved page follow what is on screen.
 */

// (The curl is offered only where there is a touch screen.)
test.use({ storageState: ADMIN_STATE, hasTouch: true });
test.setTimeout(90_000);

interface Frame {
  t: number;
  curl: number | null;
  page: number;
  shown: number[];
  layer: boolean;
  clip: string;
}

/** Every animation frame for a while after `act`: the turn's progress,
 *  the pager's position and whether the curl layer is up. */
async function record(
  page: Page,
  act: () => Promise<void>,
  ms = 2200,
): Promise<Frame[]> {
  await page.evaluate((ms) => {
    const w = window as any;
    w.__curlFrames = [];
    const t0 = performance.now();
    const step = () => {
      const p = w.__beepubReaderNG.pager;
      const layer = document.querySelector<HTMLElement>(
        '[data-testid="pager-curl"]',
      );
      const clips = layer
        ? [...layer.querySelectorAll<HTMLElement>("*")]
            .map((el) => el.style.clipPath)
            .filter((c) => c.startsWith("polygon"))
        : [];
      w.__curlFrames.push({
        t: performance.now() - t0,
        curl: p.curl,
        page: p.page,
        shown: [...p.shown],
        layer: !!layer && !layer.hidden,
        clip: clips[0] ?? "",
      });
      if (performance.now() - t0 < ms) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, ms);
  await act();
  await page.waitForTimeout(ms + 200);
  return page.evaluate(() => (window as any).__curlFrames as Frame[]);
}

/** A turn played on screen: frames part way over, the position unchanged
 *  until after the last of them, then the layer gone. */
function expectCurled(frames: Frame[], from: number, to: number) {
  const mid = frames.filter(
    (f) => f.curl != null && f.curl > 0.05 && f.curl < 0.95,
  );
  expect(mid.length).toBeGreaterThan(5);
  expect(mid.every((f) => f.layer)).toBe(true);
  expect(mid.some((f) => f.clip.startsWith("polygon("))).toBe(true);
  expect(mid.every((f) => f.page === from)).toBe(true);
  const landed = frames.findIndex((f) => f.page === to);
  expect(landed).toBeGreaterThan(frames.indexOf(mid[mid.length - 1]));
  const last = frames[frames.length - 1];
  expect(last.page).toBe(to);
  expect(last.curl).toBeNull();
  expect(last.layer).toBe(false);
}

async function pagerBox(page: Page) {
  return (await page.getByTestId("image-pager").boundingBox())!;
}

/** Tap a page-turn zone: the left or right quarter of the pager. */
async function tapSide(page: Page, side: "left" | "right") {
  const box = await pagerBox(page);
  await page.mouse.click(
    box.x + box.width * (side === "left" ? 0.1 : 0.9),
    box.y + box.height * 0.5,
  );
}

async function openCurled(page: Page) {
  const bookId = await seedFixture(page.request, CURL_BOOK);
  await openComic(page, bookId);
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));
  await setPagerSetting(page, "setting-pager-turn", "Curl");
  expect(
    await page.evaluate(() => window.__beepubReaderNG.pager.pageTurn),
  ).toBe("curl");
  return bookId;
}

test("single page: a tap curls the page over, the position moves when it lands", async ({
  page,
}) => {
  await openCurled(page);
  expect((await pagerState(page)).rtl).toBe(true);
  // A manga turns forward on the left.
  expectCurled(await record(page, () => tapSide(page, "left")), 0, 1);
  expect((await pagerState(page)).shown).toEqual([1]);
  // And back on the right: the previous sheet comes back over.
  expectCurled(await record(page, () => tapSide(page, "right")), 1, 0);
  // A key turns the same way.
  expectCurled(
    await record(page, () => page.keyboard.press("ArrowLeft")),
    0,
    1,
  );
});

test("double page: the cover, then a pair turning to a pair, both directions", async ({
  page,
}) => {
  await openCurled(page);
  await setPagerSetting(page, "setting-pager-mode", "Double page");
  expect((await pagerState(page)).shown).toEqual([0]);
  // The cover alone turns as a single sheet onto the first pair.
  expectCurled(await record(page, () => tapSide(page, "left")), 0, 1);
  expect((await pagerState(page)).shown).toEqual([2, 1]);
  // The left page lifts over the gutter: 2–3 to 4–5.
  expectCurled(await record(page, () => tapSide(page, "left")), 1, 3);
  expect((await pagerState(page)).shown).toEqual([4, 3]);
  expectCurled(await record(page, () => tapSide(page, "right")), 3, 1);
  expect((await pagerState(page)).shown).toEqual([2, 1]);

  // Read left to right, the right page turns.
  await setPagerSetting(page, "setting-pager-direction", "Left to right");
  expect((await pagerState(page)).shown).toEqual([1, 2]);
  expectCurled(await record(page, () => tapSide(page, "right")), 1, 3);
  expect((await pagerState(page)).shown).toEqual([3, 4]);
  expectCurled(await record(page, () => tapSide(page, "left")), 3, 1);
});

test("a dragged sheet is held short of turning over, and letting go finishes it", async ({
  page,
}) => {
  await openCurled(page);
  const box = await pagerBox(page);
  const y = box.y + box.height * 0.7;
  // A manga's sheet turns over to the right: drag from its left part far
  // past the spine, to the pager's edge.
  await page.mouse.move(box.x + box.width * 0.35, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 4, y, { steps: 24 });
  await page.waitForTimeout(400);
  const held = await page.evaluate(() => window.__beepubReaderNG.pager.curl);
  expect(held).not.toBeNull();
  // Held: past half way, short of over (0.6 and a little give).
  expect(held).toBeGreaterThan(0.5);
  expect(held).toBeLessThan(0.67);
  expect((await pagerState(page)).page).toBe(0);
  await page.mouse.up();
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(1);
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.pager.curl))
    .toBeNull();

  // Brought back, the previous sheet comes over the spine at once, as
  // far as the lead, before the finger has gone anywhere.
  await page.mouse.move(box.x + box.width * 0.7, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.7 - 16, y, { steps: 3 });
  await page.waitForTimeout(500);
  const lead = await page.evaluate(() => window.__beepubReaderNG.pager.curl);
  expect(lead).toBeGreaterThan(0.72);
  expect(lead).toBeLessThan(0.86);
  await page.mouse.up();
  await expect.poll(() => pagerState(page).then((s) => s.page)).toBe(0);

  // A drag let go early falls back: the page stays.
  await page.mouse.move(box.x + box.width * 0.35, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.35 + 30, y, { steps: 15 });
  await page.waitForTimeout(300);
  await page.mouse.up();
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.pager.curl))
    .toBeNull();
  expect((await pagerState(page)).page).toBe(0);
});

test("the turn is remembered, shown only for paged modes, and instant when zoomed or motion is reduced", async ({
  page,
}) => {
  const bookId = await openCurled(page);
  expect(
    await page.evaluate(() => localStorage.getItem("reader-pager-turn")),
  ).toBe("curl");
  await page.reload();
  await openComic(page, bookId);
  expect(
    await page.evaluate(() => window.__beepubReaderNG.pager.pageTurn),
  ).toBe("curl");

  // A strip scrolls: no turn to choose.
  await setPagerSetting(page, "setting-pager-mode", "Continuous vertical");
  await page.getByRole("button", { name: "Reader settings" }).click();
  await expect(page.getByTestId("setting-pager-turn")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await setPagerSetting(page, "setting-pager-mode", "Single page");
  await page.evaluate(() => window.__beepubReaderNG.pager.goTo(0));

  // Zoomed in, a turn is at once (and lets go of the zoom).
  const box = await pagerBox(page);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -400);
  await page.keyboard.up("Control");
  await expect
    .poll(() => pagerState(page).then((s) => s.scale))
    .toBeGreaterThan(1);
  let frames = await record(page, () => page.keyboard.press("ArrowLeft"), 600);
  expect(frames.every((f) => f.curl == null)).toBe(true);
  expect((await pagerState(page)).page).toBe(1);

  // Reduced motion: at once.
  await page.emulateMedia({ reducedMotion: "reduce" });
  frames = await record(page, () => tapSide(page, "left"), 600);
  expect(frames.every((f) => f.curl == null)).toBe(true);
  expect((await pagerState(page)).page).toBe(2);
});
