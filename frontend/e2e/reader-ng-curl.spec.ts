import {
  test,
  expect,
  devices,
  type CDPSession,
  type Page,
} from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  ANCHOR_BOOK,
  CHAPTER_ANCHORS_BOOK,
  VERTICAL_LONG_BOOK,
  iphone,
  openBook,
  seedFixture,
  touchTap,
} from "./ng-helpers";

/**
 * reader-ng: the curl page turn. The same two sheets as the slide (the
 * live page and a ghost of the page a turn away, slide.ts), drawn the
 * other way: nothing moves; the sheet with the lower page number is cut
 * along a fold and the flap folded over the spine (curl.ts). A finger
 * lifts it only so far and letting go finishes the turn; a page brought
 * back comes over by itself first; taps and keys play the whole turn.
 *
 * Read through the debug handle: `core.curlFold` is the fold on screen
 * ({ over: 0 flat … 1 turned over, sheet }) or null.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });
test.setTimeout(90_000);

type Point = { x: number; y: number };

function touchDown(cdp: CDPSession, at: Point) {
  return cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [at],
  });
}

async function touchMove(
  cdp: CDPSession,
  from: Point,
  to: Point,
  steps: number,
) {
  for (let i = 1; i <= steps; i++) {
    await new Promise((resolve) => setTimeout(resolve, 16));
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        {
          x: from.x + ((to.x - from.x) * i) / steps,
          y: from.y + ((to.y - from.y) * i) / steps,
        },
      ],
    });
  }
}

function touchUp(cdp: CDPSession) {
  return cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
}

const at = (x: number): Point => ({ x, y: 600 });

interface State {
  index: number;
  page: number;
  pages: number;
  text: string;
  /** The fold on screen: how far over, and whether the live page (or a
   *  ghost) is the sheet folded. */
  over: number | null;
  sheet: "live" | "ghost" | null;
  /** The clip path on the folded sheet. */
  clip: string;
}

function state(page: Page): Promise<State> {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    const fold = core.curlFold;
    const sheet = fold?.sheet ?? null;
    return {
      index: paginator.getContents()[0]?.index ?? -1,
      page: paginator.page,
      pages: paginator.pages,
      text: core.lastLocation?.range?.toString() ?? "",
      over: fold ? fold.over : null,
      sheet: sheet ? (sheet === paginator ? "live" : "ghost") : null,
      clip: sheet ? sheet.style.clipPath : "",
    };
  });
}

/** At rest: no fold, no sheet cut, the live page taking touches. */
function settled(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    if (core.curlFold) return false;
    if (paginator.style.clipPath) return false;
    if (getComputedStyle(paginator).pointerEvents === "none") return false;
    return (core.ghosts as HTMLElement[]).every((g) => !g.style.clipPath);
  });
}

/** Wait until the ghost shows the page one turn away in `dir`. */
async function ghostReady(page: Page, dir: 1 | -1 = 1) {
  await expect
    .poll(
      () =>
        page.evaluate((dir) => {
          const { core, paginator } = window.__beepubReaderNG;
          const g = core.ghostFor(dir);
          if (!g) return false;
          try {
            const li = paginator.getContents()[0].index;
            const gi = g.getContents()[0]?.index;
            if (dir > 0)
              return paginator.page < paginator.pages - 2
                ? gi === li && g.page === paginator.page + 1
                : gi > li && g.page === 1;
            return paginator.page > 1
              ? gi === li && g.page === paginator.page - 1
              : gi < li && g.page === g.pages - 2;
          } catch {
            return false;
          }
        }, dir),
      { timeout: 10_000 },
    )
    .toBe(true);
  await page.waitForTimeout(100);
}

/** Record how far over the fold is on every frame from here on. */
function recordFold(page: Page) {
  return page.evaluate(() => {
    const w = window as any;
    w.__overs = [];
    const tick = () => {
      const fold = w.__beepubReaderNG.core.curlFold;
      w.__overs.push(fold ? fold.over : null);
      if (w.__overs.length < 240) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

function folds(page: Page): Promise<(number | null)[]> {
  return page.evaluate(() => (window as any).__overs ?? []);
}

/** The x values of a CSS polygon(). */
function xs(clip: string): number[] {
  return [...clip.matchAll(/(-?[\d.]+)px (-?[\d.]+)px/g)].map((m) => +m[1]);
}

test("a horizontal book: the page on screen is folded over its left edge as far as the finger lifts it, and no further; let go, the turn finishes; the previous page comes back over by itself", async ({
  page,
  context,
}, testInfo) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await openBook(page, bookId, { turn: "curl", size: "24" }, ANCHOR_BOOK);
  expect(
    await page.evaluate(() => window.__beepubReaderNG.core.effectivePageTurn()),
  ).toBe("curl");
  const cdp = await context.newCDPSession(page);
  await ghostReady(page, 1);
  const rest = await state(page);
  expect(rest.pages - 2).toBeGreaterThanOrEqual(3);
  expect(rest.over).toBeNull();
  const width = page.viewportSize()!.width;

  // Forward: the finger takes the page near its right edge and goes all
  // the way to the left edge. The page on screen is the sheet; it is cut
  // along the fold, still lying along the spine on the left.
  await touchDown(cdp, at(width - 40));
  await touchMove(cdp, at(width - 40), at(4), 14);
  await expect
    .poll(async () => (await state(page)).over ?? 0)
    .toBeGreaterThan(0.4);
  await page.waitForTimeout(150);
  const mid = await state(page);
  expect(mid.sheet).toBe("live");
  // Held short of a whole turn (curl.ts: 0.6, and a little give).
  expect(mid.over!).toBeLessThan(0.66);
  const cut = xs(mid.clip);
  expect(Math.min(...cut)).toBeLessThanOrEqual(1);
  expect(Math.max(...cut)).toBeLessThan(width - 20);
  // The reader has not moved yet.
  expect(mid.page).toBe(rest.page);
  // The flap's back is the same page, seen through the paper.
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.core.curlBack))
    .toEqual({ index: rest.index, page: rest.page, showing: true });
  await page.screenshot({ path: testInfo.outputPath("mid-curl.png") });
  await touchUp(cdp);
  await expect.poll(async () => (await state(page)).page).toBe(rest.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  const next = await state(page);
  expect(next.text).not.toBe(rest.text);

  // A short, slow lift falls back onto the same page.
  await ghostReady(page, 1);
  await touchDown(cdp, at(width - 40));
  await touchMove(cdp, at(width - 40), at(width - 90), 8);
  await expect
    .poll(async () => (await state(page)).over ?? 0)
    .toBeGreaterThan(0);
  await page.waitForTimeout(250);
  await touchUp(cdp);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await state(page)).page).toBe(next.page);

  // Back: a small pull from the left, and the previous page comes over
  // the spine by itself as far as LEAD (0.8 over: a fifth of it shows),
  // over the page on screen. (The ghost steps onto it as the pull
  // begins; the sheet joins when it is there.)
  await touchDown(cdp, at(40));
  await touchMove(cdp, at(40), at(56), 3);
  await page.waitForTimeout(400);
  const back = await state(page);
  expect(back.sheet).toBe("ghost");
  expect(back.over!).toBeGreaterThan(0.7);
  expect(back.over!).toBeLessThan(0.86);
  expect(back.page).toBe(next.page);
  // Its back is the previous page's.
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.core.curlBack))
    .toEqual({ index: rest.index, page: rest.page, showing: true });
  await touchUp(cdp);
  await expect.poll(async () => (await state(page)).page).toBe(rest.page);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await state(page)).text).toBe(rest.text);
});

test("taps and keys play the whole curl and land each turn; a vertical book folds over its right edge; reduced motion jumps", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "curl", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  expect(
    await page.evaluate(() => {
      const core = window.__beepubReaderNG.core;
      return [core.vertical, core.advancesLeftward()];
    }),
  ).toEqual([true, true]);
  const cdp = await context.newCDPSession(page);
  await ghostReady(page, 1);
  const rest = await state(page);
  test.skip(
    rest.pages - 2 < 3,
    "vertical fragmentation degenerate — CJK fonts missing",
  );
  const width = page.viewportSize()!.width;

  // A key: the fold goes from flat to over, frame by frame, before the
  // page is reached.
  await recordFold(page);
  await page.keyboard.press("PageDown");
  await expect.poll(async () => (await state(page)).page).toBe(rest.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  const played = (await folds(page)).filter((o): o is number => o != null);
  expect(played.length).toBeGreaterThan(5);
  expect(played.some((o) => o > 0.2 && o < 0.8)).toBe(true);
  // (Over, never back and forth.)
  for (let i = 1; i < played.length; i++)
    expect(played[i]).toBeGreaterThanOrEqual(played[i - 1] - 1e-6);

  // The finger, forward in a book that advances leftward: from the left
  // edge to the right. The page is still lying along the spine on the
  // right.
  await ghostReady(page, 1);
  await touchDown(cdp, at(40));
  await touchMove(cdp, at(40), at(width - 120), 10);
  await expect
    .poll(async () => (await state(page)).over ?? 0)
    .toBeGreaterThan(0.3);
  const mid = await state(page);
  expect(mid.sheet).toBe("live");
  const cut = xs(mid.clip);
  expect(Math.max(...cut)).toBeGreaterThanOrEqual(width - 1);
  expect(Math.min(...cut)).toBeGreaterThan(20);
  await touchUp(cdp);
  await expect.poll(async () => (await state(page)).page).toBe(rest.page + 2);
  await expect.poll(() => settled(page)).toBe(true);

  // A tap on the right of a leftward book turns back.
  await touchTap(cdp, { x: width - 30, y: 420 }, 60);
  await expect.poll(async () => (await state(page)).page).toBe(rest.page + 1);
  await expect.poll(() => settled(page)).toBe(true);

  // Quick paging lands every turn.
  await page.keyboard.press("PageDown");
  await page.waitForTimeout(80);
  await page.keyboard.press("PageDown");
  await expect.poll(async () => (await state(page)).page).toBe(rest.page + 3);
  await expect.poll(() => settled(page)).toBe(true);

  // Reduced motion: a bare jump, no fold at all.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await recordFold(page);
  await page.keyboard.press("PageUp");
  await expect.poll(async () => (await state(page)).page).toBe(rest.page + 2);
  await page.waitForTimeout(300);
  expect((await folds(page)).filter((o) => o != null)).toEqual([]);
});

test("across a chapter boundary the curl turns onto the next chapter's first page and back onto the last one", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "curl", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  await page.evaluate(
    () => void window.__beepubReaderNG.core.goTo({ index: 0, fraction: 1 }),
  );
  await expect
    .poll(async () => {
      const s = await state(page);
      return s.index === 0 && s.page === s.pages - 2;
    })
    .toBe(true);
  await ghostReady(page, 1);
  const end = await state(page);

  await recordFold(page);
  await page.keyboard.press("PageDown");
  await expect
    .poll(async () => {
      const s = await state(page);
      return s.index === 1 && s.page === 1;
    })
    .toBe(true);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await folds(page)).some((o) => o != null && o > 0.2)).toBe(true);
  // The chapter named and the place saved are the new chapter's.
  expect(
    await page.evaluate(() => window.__beepubReaderNG.core.lastLocation?.index),
  ).toBe(1);

  await ghostReady(page, -1);
  await recordFold(page);
  await page.keyboard.press("PageUp");
  await expect
    .poll(async () => {
      const s = await state(page);
      return s.index === 0 && s.page === s.pages - 2;
    })
    .toBe(true);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await folds(page)).some((o) => o != null && o < 0.8)).toBe(true);
  expect((await state(page)).text).toBe(end.text);
});

test("Curl is chosen in the settings and kept", async ({ page, context }) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await page.addInitScript(() => {
    // Once: the reload below is to find the choice kept.
    try {
      if (!sessionStorage.getItem("curl-spec")) {
        sessionStorage.setItem("curl-spec", "1");
        localStorage.removeItem("reader-page-turn");
      }
    } catch {
      // no storage
    }
  });
  await openBook(page, bookId, { turn: "" }, ANCHOR_BOOK);
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  const bar = page.getByRole("toolbar", { name: "Reading controls" });
  await expect(bar).toBeVisible();
  await bar.getByRole("button", { name: "Reader settings" }).click();
  await page.getByRole("button", { name: "Curl", exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(() => window.__beepubReaderNG.core.effectivePageTurn()),
    )
    .toBe("curl");
  expect(
    await page.evaluate(() => localStorage.getItem("reader-page-turn")),
  ).toBe("curl");
  await page.reload();
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
  );
  expect(
    await page.evaluate(() => window.__beepubReaderNG.core.effectivePageTurn()),
  ).toBe("curl");
});

test.describe("on an iPad", () => {
  const { defaultBrowserType: _webkit, ...ipad } = devices["iPad Pro 11"];
  test.use({ ...ipad });

  test("after a font size change the flap's back still shows the page through the paper (vertical text, a page height snapped to its lines)", async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, VERTICAL_LONG_BOOK);
    await openBook(page, bookId, { turn: "curl" }, VERTICAL_LONG_BOOK);
    const cdp = await context.newCDPSession(page);
    const y = 700;
    for (const button of ["Increase font size", "Increase font size"]) {
      await page.getByRole("button", { name: "Reader settings" }).click();
      await page.getByRole("button", { name: button }).click();
      await page.keyboard.press("Escape");
      await page.waitForTimeout(1000);
      // Forward in vertical text: from the left edge toward the spine.
      await touchDown(cdp, { x: 40, y });
      await touchMove(cdp, { x: 40, y }, { x: 300, y }, 10);
      await expect
        .poll(() =>
          page.evaluate(() => {
            const { core, paginator } = window.__beepubReaderNG;
            const back = core.curlBack;
            return (
              back && {
                ...back,
                live: [paginator.getContents()[0]?.index, paginator.page],
              }
            );
          }),
        )
        .toMatchObject({ showing: true });
      const at = await page.evaluate(() => {
        const { core, paginator } = window.__beepubReaderNG;
        return {
          back: [core.curlBack!.index, core.curlBack!.page],
          live: [paginator.getContents()[0]?.index, paginator.page],
        };
      });
      expect(at.back).toEqual(at.live);
      // Laid back down where it was.
      await touchMove(cdp, { x: 300, y }, { x: 40, y }, 10);
      await touchUp(cdp);
      await expect.poll(() => settled(page)).toBe(true);
    }
  });
});
