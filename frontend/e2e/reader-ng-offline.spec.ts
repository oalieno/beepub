import {
  devices,
  test,
  expect,
  type BrowserContext,
  type Page,
  type Route,
} from "@playwright/test";
import { percentFromPosition } from "../src/lib/reading/progress";
import { ADMIN_STATE } from "./helpers";
import {
  NINE_CHAPTERS_BOOK,
  iphone,
  marks,
  openBook,
  pointOnWord,
  resetProgress,
  seedFixture,
  touchTap,
} from "./ng-helpers";

/**
 * reader-ng: a chapter that is not there yet, and one that will not come.
 *
 * A streamed book's sections are fetched as they are reached (the
 * prefetch keeps a few ahead). The rule under test: a load that has not
 * succeeded never changes where the reader is. While a chapter is on its
 * way the page, the chapter named, the percentage and the saved position
 * stay those of the page the reader came from; a turn onto it shows bare
 * paper (the slide slides over it, the fade fades to it), a jump leaves
 * the page as it is, and a small spinner comes up when the wait gets
 * long. A chapter that fails to load leaves the reader where they were,
 * with a notice that offers to try again — and, offline, the table of
 * contents marks the chapters that are not in memory.
 *
 * Offline nothing is refused unasked. The mark says the chapter is not
 * at hand; a tap on it, a seek, a page turn each ask for the chapter
 * once (the browser's HTTP cache may hold it, the connection may be
 * back before the app has heard), and a request that cannot go out
 * fails at once. While a marked entry is being asked for it shows a
 * spinner where its mark was; the list closes when the chapter comes
 * and stays when it does not.
 *
 * The notice is a toast like any other: in the toasts' column (clear
 * of the phone's bottom bar while that shows), beside whatever else is
 * being said, and gone by itself after a while — and the failure goes
 * with it: the connection returning opens the chapter only while the
 * toast is still showing, never after. Its Retry takes it down and asks
 * again (the reader's own spinner covers a long wait); an attempt that
 * fails brings it back, and one that fails while it is showing starts
 * its time over and shakes it (`data-repeats`).
 *
 * Every test routes the book's content requests (`gate`), which also
 * keeps the browser's HTTP cache out of it: what is "not fetched" here
 * really has to come over the network.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });
test.setTimeout(90_000);

const CONTENT = "**/api/books/*/content/**";

interface Gate {
  /** Hold requests whose path contains `part` until the returned
   *  function is called. */
  hold(part: string): () => void;
  /** Fail requests whose path contains `part`; the returned function
   *  lets them through again. */
  fail(part: string): () => void;
}

async function gate(page: Page): Promise<Gate> {
  const held = new Map<string, Promise<void>>();
  const failing = new Set<string>();
  await page.route(CONTENT, async (route: Route) => {
    const url = decodeURIComponent(route.request().url());
    for (const part of failing) if (url.includes(part)) return route.abort();
    for (const [part, released] of held) if (url.includes(part)) await released;
    // (A request that was held can be let go into a failure.)
    for (const part of failing) if (url.includes(part)) return route.abort();
    await route.continue().catch(() => {});
  });
  return {
    hold(part) {
      let release: () => void = () => {};
      held.set(part, new Promise((resolve) => (release = resolve)));
      return () => {
        held.delete(part);
        release();
      };
    },
    fail(part) {
      failing.add(part);
      return () => failing.delete(part);
    },
  };
}

/** Everything that says where the reader is. */
function where(page: Page) {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    const l = core.lastLocation;
    const banner = document.querySelector('[role="banner"]')!;
    const lines = Array.from(banner.querySelectorAll("p"), (p) =>
      (p.textContent ?? "").trim(),
    );
    return {
      index: l.index as number,
      fraction: l.fraction as number,
      cfi: l.startCfi as string,
      live: paginator.getContents()[0]?.index as number,
      label: lines[1] ?? null,
      percent:
        document
          .querySelector('[data-testid="reader-percent"]')
          ?.textContent?.trim() ?? null,
    };
  });
}

function available(page: Page, index: number): Promise<boolean> {
  return page.evaluate(
    (index) => window.__beepubReaderNG.core.sectionAvailable(index),
    index,
  );
}

function goTo(page: Page, target: unknown) {
  return page.evaluate(
    (target) => window.__beepubReaderNG.core.goTo(target),
    target,
  );
}

const notice = (page: Page) =>
  page.locator(".toast-position").getByTestId("reader-load-notice");
/** One notice, and no other on its way out: after a Retry the toast
 *  that was clicked leaves as the next one comes. */
async function oneNotice(page: Page) {
  await page.waitForTimeout(400);
  await expect(notice(page)).toHaveCount(1);
}
const spinner = (page: Page) => page.getByTestId("reader-pending");
const tocDialog = (page: Page) =>
  page.getByRole("dialog", { name: "Table of Contents" });

async function openToc(page: Page, context: BrowserContext) {
  const bar = page.getByRole("toolbar", { name: "Reading controls" });
  if (!(await bar.isVisible())) {
    const cdp = await context.newCDPSession(page);
    await touchTap(cdp, { x: 195, y: 420 }, 60);
  }
  await bar.getByRole("button", { name: "Table of Contents" }).click();
  await expect(tocDialog(page)).toBeVisible();
}

const entry = (page: Page, name: string) =>
  tocDialog(page).getByRole("button", { name, exact: true });

/** The content requests made for the file whose path contains `part`. */
function requests(page: Page, part: string): string[] {
  const asked: string[] = [];
  page.on("request", (r) => {
    const url = decodeURIComponent(r.url());
    if (url.includes("/content/") && url.includes(part)) asked.push(url);
  });
  return asked;
}

/** Answer requests for `part` from outside the browser — what the HTTP
 *  cache does for a chapter it holds: the page is still offline. The
 *  returned function stops it. */
async function serveOffline(page: Page, part: string) {
  const handler = async (route: Route) => {
    const url = decodeURIComponent(route.request().url());
    if (!url.includes(part)) return route.fallback();
    const response = await route.fetch();
    await route.fulfill({ response });
  };
  await page.route(CONTENT, handler);
  return () => page.unroute(CONTENT, handler);
}

/** The bare paper a pending turn shows: the slide's sheet, or the page
 *  faded out. */
function onPaper(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const { paginator } = window.__beepubReaderNG;
    const blank = document.querySelector<HTMLElement>("[data-beepub-blank]");
    if (blank && getComputedStyle(blank).display !== "none") {
      const r = blank.getBoundingClientRect();
      return r.left === 0 && getComputedStyle(blank).zIndex === "7";
    }
    return getComputedStyle(paginator).opacity === "0";
  });
}

/** No paper, no sheet out of place: the page is the reader's. */
function atRest(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    const blank = document.querySelector<HTMLElement>("[data-beepub-blank]");
    if (blank && getComputedStyle(blank).display !== "none") return false;
    const style = getComputedStyle(paginator);
    return (
      style.opacity === "1" &&
      paginator.getBoundingClientRect().left === 0 &&
      paginator.getAnimations().length === 0 &&
      !core.cover
    );
  });
}

interface Watch {
  errors: string[];
  saves: { cfi: string; percentage: number | null }[];
}

/** Uncaught errors (unhandled rejections among them) and every progress
 *  save the page attempts. */
function watch(page: Page): Watch {
  const seen: Watch = { errors: [], saves: [] };
  page.on("pageerror", (e) => seen.errors.push(e.message));
  page.on("request", (r) => {
    if (r.method() !== "PUT" || !r.url().endsWith("/progress")) return;
    const body = r.postDataJSON();
    seen.saves.push({ cfi: body.cfi, percentage: body.percentage });
  });
  return seen;
}

async function open(page: Page, turn: string) {
  const seen = watch(page);
  const g = await gate(page);
  const bookId = await seedFixture(page.request, NINE_CHAPTERS_BOOK);
  await resetProgress(page.request, bookId);
  await openBook(page, bookId, { turn }, NINE_CHAPTERS_BOOK);
  // The prefetch has what it reaches for from the first page.
  await expect.poll(() => available(page, 3)).toBe(true);
  await page.waitForTimeout(300);
  return { seen, gate: g, bookId };
}

/** What every one of these tests ends on. */
function expectSound(seen: Watch) {
  expect(seen.errors).toEqual([]);
  for (const save of seen.saves) {
    expect(save.cfi).not.toContain("NaN");
    expect(typeof save.percentage).toBe("number");
  }
}

test("the percentage is a number whatever position it is given", () => {
  const weights = [3, 1, 6];
  expect(percentFromPosition(weights, 1, 0.5)).toBe(35);
  for (const index of [undefined, NaN, null, -1, 99, Infinity])
    for (const fraction of [undefined, NaN, 0.5, Infinity, -Infinity]) {
      const value = percentFromPosition(
        weights,
        index as number,
        fraction as number,
      );
      expect(Number.isFinite(value)).toBe(true);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(100);
    }
  expect(percentFromPosition([], NaN, NaN)).toBe(0);
  expect(percentFromPosition([0, 0], 1, 0.5)).toBe(0);
});

for (const turn of ["fade", "slide"] as const) {
  test.describe(`page turns: ${turn}`, () => {
    test("offline, a chapter picked from the table of contents that is not loaded: marked, asked for, and when it does not come the reader stays put with a notice; back online it opens", async ({
      page,
      context,
    }) => {
      const { seen } = await open(page, turn);
      expect(await available(page, 8)).toBe(false);
      const before = await where(page);
      expect(before).toMatchObject({ index: 0, label: "啟航", percent: "0%" });

      await context.setOffline(true);
      const asked = requests(page, "c-009");
      await openToc(page, context);
      const dialog = tocDialog(page);
      // What is in memory is not marked; what is not, is — and a marked
      // entry is still an entry: described, not disabled.
      for (const name of ["啟航", "霧號", "潮表", "燈語"]) {
        await expect(entry(page, name)).not.toHaveAttribute(
          "data-toc-unavailable",
        );
        await expect(entry(page, name).locator("svg")).toHaveCount(0);
      }
      for (const name of ["渡客", "夜泊", "修纜", "歸港", "版權頁"]) {
        await expect(entry(page, name)).toHaveAttribute(
          "data-toc-unavailable",
        );
        await expect(entry(page, name)).not.toHaveAttribute("aria-disabled");
        await expect(entry(page, name)).toBeEnabled();
        await expect(entry(page, name)).toHaveAttribute("title", /offline/i);
        await expect(entry(page, name)).toHaveAccessibleDescription(
          /offline/i,
        );
        await expect(entry(page, name).locator("svg")).toBeVisible();
      }

      // A tap asks for the chapter. It does not come.
      await entry(page, "版權頁").click();
      await expect(notice(page)).toContainText("offline");
      await expect(notice(page).getByRole("button", { name: "Retry" })).toBeVisible();
      expect(asked.length).toBe(1);
      // The list stays, the entry is marked as it was; the page behind
      // it has not moved.
      await expect(dialog).toBeVisible();
      await expect(entry(page, "版權頁")).not.toHaveAttribute("data-toc-trying");
      await expect(entry(page, "版權頁")).toHaveAttribute("data-toc-unavailable");
      expect(await where(page)).toEqual(before);
      expect(asked.length).toBe(1);
      await dialog.getByRole("button", { name: "Close" }).click();

      // Still a reader: forward, back, and a chapter that is in memory.
      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).fraction).toBeGreaterThan(0);
      await expect(notice(page)).toBeHidden();
      await page.keyboard.press("PageUp");
      await expect.poll(async () => (await where(page)).fraction).toBe(0);
      await expect.poll(() => atRest(page)).toBe(true);
      expect((await where(page)).percent).toMatch(/^\d+%$/);

      // Nothing was saved but the page the reader was on.
      await page.waitForTimeout(2600);
      for (const save of seen.saves) expect(save.cfi).toMatch(/^epubcfi\(\/6\/2!/);

      // Asked for again, then the connection returns: it opens by itself.
      await openToc(page, context);
      await entry(page, "版權頁").click();
      await expect(notice(page)).toBeVisible();
      await expect(entry(page, "版權頁")).not.toHaveAttribute("data-toc-trying");
      await context.setOffline(false);
      await expect
        .poll(async () => (await where(page)).index, { timeout: 15_000 })
        .toBe(8);
      await expect(notice(page)).toBeHidden();
      await expect(dialog).toBeHidden();
      await expect
        .poll(async () => (await where(page)).label)
        .toBe("版權頁");
      expect((await where(page)).live).toBe(8);

      // Online, nothing is marked, and an entry is an entry.
      await openToc(page, context);
      await expect(dialog.locator("[data-toc-unavailable]")).toHaveCount(0);
      await dialog.getByRole("button", { name: "渡客" }).click();
      await expect.poll(async () => (await where(page)).index).toBe(4);
      await expect(dialog).toBeHidden();
      expectSound(seen);
    });

    test("offline, paging forward into a chapter that is not loaded leaves the reader on the last page; back online the turn is made", async ({
      page,
      context,
    }) => {
      const { seen } = await open(page, turn);
      expect(await available(page, 4)).toBe(false);
      await context.setOffline(true);
      await goTo(page, { index: 3, fraction: 1 });
      await expect.poll(async () => (await where(page)).index).toBe(3);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.waitForTimeout(400);
      const before = await where(page);
      expect(before.label).toBe("燈語");
      expect(await available(page, 4)).toBe(false);

      // (The turn asks for the chapter too.)
      const asked = requests(page, "c-005");
      await page.keyboard.press("PageDown");
      await expect(notice(page)).toContainText("offline");
      await expect.poll(() => atRest(page)).toBe(true);
      expect(await where(page)).toEqual(before);
      expect(asked.length).toBeGreaterThan(0);

      // Once more: the same answer, nothing piles up.
      await page.keyboard.press("PageDown");
      await page.waitForTimeout(600);
      await expect.poll(() => atRest(page)).toBe(true);
      expect(await where(page)).toEqual(before);

      // The other way still turns, and comes back.
      await page.keyboard.press("PageUp");
      await expect
        .poll(async () => (await where(page)).fraction)
        .toBeLessThan(before.fraction);
      await expect(notice(page)).toBeHidden();
      await expect.poll(() => atRest(page)).toBe(true);
      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).cfi).toBe(before.cfi);
      await expect.poll(() => atRest(page)).toBe(true);

      await page.keyboard.press("PageDown");
      await expect(notice(page)).toBeVisible();
      await page.waitForTimeout(2600);
      for (const save of seen.saves) expect(save.cfi).toMatch(/^epubcfi\(\/6\/(2|8)!/);

      await context.setOffline(false);
      await expect
        .poll(async () => (await where(page)).index, { timeout: 15_000 })
        .toBe(4);
      await expect(notice(page)).toBeHidden();
      expect(await where(page)).toMatchObject({
        fraction: 0,
        label: "渡客",
        live: 4,
      });
      // And reading on is reading on.
      await expect.poll(() => atRest(page)).toBe(true);
      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).fraction).toBeGreaterThan(0);
      expectSound(seen);
    });

    test("offline, paging back into a chapter that is not loaded leaves the reader on the first page; back online they land on its last", async ({
      page,
      context,
    }) => {
      const { seen } = await open(page, turn);
      await goTo(page, 6);
      await expect.poll(async () => (await where(page)).index).toBe(6);
      await expect.poll(() => available(page, 5)).toBe(true);
      await page.waitForTimeout(500);
      expect(await available(page, 4)).toBe(false);
      await context.setOffline(true);
      await goTo(page, { index: 5, fraction: 0 });
      await expect.poll(async () => (await where(page)).index).toBe(5);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.waitForTimeout(400);
      const before = await where(page);
      expect(before).toMatchObject({ fraction: 0, label: "夜泊" });

      await page.keyboard.press("PageUp");
      await expect(notice(page)).toContainText("offline");
      await expect.poll(() => atRest(page)).toBe(true);
      expect(await where(page)).toEqual(before);

      await context.setOffline(false);
      await expect
        .poll(async () => (await where(page)).index, { timeout: 15_000 })
        .toBe(4);
      await expect(notice(page)).toBeHidden();
      const landed = await page.evaluate(() => {
        const { paginator } = window.__beepubReaderNG;
        return { page: paginator.page, pages: paginator.pages };
      });
      expect(landed.page).toBe(landed.pages - 2);
      expect((await where(page)).label).toBe("渡客");
      expectSound(seen);
    });

    test("a slow chapter: the turn is made onto bare paper, a spinner comes up only when the wait is long, and nothing says the reader has moved until the page is there", async ({
      page,
    }) => {
      const { seen, gate } = await open(page, turn);
      // Count every time the spinner is put up.
      await page.evaluate(() => {
        (window as any).__spins = 0;
        new MutationObserver(() => {
          if (document.querySelector('[data-testid="reader-pending"]')) {
            (window as any).__spins++;
            (window as any).__spunAt = performance.now();
          }
        }).observe(document.querySelector('[data-testid="book-reader"]')!, {
          childList: true,
        });
      });
      const spins = () => page.evaluate(() => (window as any).__spins as number);
      const release = gate.hold("c-005");

      // A chapter already in memory: turned into with no spinner at all.
      await goTo(page, { index: 0, fraction: 1 });
      await expect.poll(() => atRest(page)).toBe(true);
      await page.waitForTimeout(300);
      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).index).toBe(1);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.waitForTimeout(600);
      expect(await spins()).toBe(0);

      await goTo(page, { index: 3, fraction: 1 });
      await expect.poll(async () => (await where(page)).index).toBe(3);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.waitForTimeout(400);
      const before = await where(page);

      await page.evaluate(() => {
        window.addEventListener(
          "keydown",
          () => ((window as any).__askedAt = performance.now()),
          { capture: true, once: true },
        );
      });
      await page.keyboard.press("PageDown");
      await expect.poll(() => onPaper(page)).toBe(true);
      // The wait being long, a spinner comes up — not at once.
      await expect(spinner(page)).toBeVisible();
      expect(
        await page.evaluate(
          () => (window as any).__spunAt - (window as any).__askedAt,
        ),
      ).toBeGreaterThanOrEqual(400);
      expect(await spins()).toBe(1);
      expect(await where(page)).toEqual(before);
      await page.waitForTimeout(700);
      expect(await onPaper(page)).toBe(true);
      expect(await where(page)).toEqual(before);

      release();
      await expect.poll(async () => (await where(page)).index).toBe(4);
      await expect(spinner(page)).toHaveCount(0);
      await expect.poll(() => atRest(page)).toBe(true);
      expect(await where(page)).toMatchObject({
        fraction: 0,
        label: "渡客",
        live: 4,
      });
      if (turn === "slide") {
        // It slid, over the paper; it did not fade.
        const log = await page.evaluate(() =>
          (window.__beepubReaderNG.core.slideLog as any[]).filter((e) => e.how),
        );
        expect(log.filter((e) => e.how === "fade")).toEqual([]);
        expect(log.at(-1)).toMatchObject({ dir: 1, how: "slide", blank: true });
      }
      expect(await notice(page).count()).toBe(0);
      expectSound(seen);
    });

    test("turning back from the bare paper gives the slow chapter up, and the reader is where they were", async ({
      page,
    }) => {
      const { seen, gate } = await open(page, turn);
      const release = gate.hold("c-005");
      await goTo(page, { index: 3, fraction: 1 });
      await expect.poll(async () => (await where(page)).index).toBe(3);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.waitForTimeout(400);
      const before = await where(page);

      await page.keyboard.press("PageDown");
      await expect.poll(() => onPaper(page)).toBe(true);
      await expect(spinner(page)).toBeVisible();
      await page.keyboard.press("PageUp");
      await expect.poll(() => atRest(page)).toBe(true);
      await expect(spinner(page)).toHaveCount(0);
      expect(await where(page)).toEqual(before);

      // The chapter arriving now moves nobody.
      release();
      await expect.poll(() => available(page, 4)).toBe(true);
      await page.waitForTimeout(800);
      expect(await where(page)).toEqual(before);
      expect(await notice(page).count()).toBe(0);

      // The page before is one turn away, and the chapter one turn on.
      await page.keyboard.press("PageUp");
      await expect
        .poll(async () => (await where(page)).fraction)
        .toBeLessThan(before.fraction);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).cfi).toBe(before.cfi);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).index).toBe(4);
      expectSound(seen);
    });

    test("a jump to a slow chapter keeps the page until it is there; a page turn meanwhile gives the jump up", async ({
      page,
      context,
    }) => {
      const { seen, gate } = await open(page, turn);
      const release = gate.hold("c-009");
      const before = await where(page);
      await openToc(page, context);
      await tocDialog(page).getByRole("button", { name: "版權頁" }).click();
      await expect(tocDialog(page)).toBeHidden();
      await expect(spinner(page)).toBeVisible();
      // The page is still the page, named and counted as before.
      expect(await atRest(page)).toBe(true);
      expect(await where(page)).toEqual(before);

      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).fraction).toBeGreaterThan(0);
      await expect(spinner(page)).toHaveCount(0);
      const turned = await where(page);
      expect(turned.index).toBe(0);
      release();
      await expect.poll(() => available(page, 8)).toBe(true);
      await page.waitForTimeout(800);
      expect((await where(page)).cfi).toBe(turned.cfi);

      // Asked for again, it is there.
      await openToc(page, context);
      await tocDialog(page).getByRole("button", { name: "版權頁" }).click();
      await expect.poll(async () => (await where(page)).index).toBe(8);
      expect(await notice(page).count()).toBe(0);
      expectSound(seen);
    });

    test("a chapter that fails to load: the reader stays, the notice says so, and Retry opens it", async ({
      page,
      context,
    }) => {
      const { seen, gate } = await open(page, turn);
      const before = await where(page);

      // By the table of contents.
      let mend = gate.fail("c-009");
      await openToc(page, context);
      await tocDialog(page).getByRole("button", { name: "版權頁" }).click();
      await expect(notice(page)).toContainText("couldn't be loaded");
      await expect.poll(() => atRest(page)).toBe(true);
      expect(await where(page)).toEqual(before);
      // Again, still failing: the same notice, the same page.
      await notice(page).getByRole("button", { name: "Retry" }).click();
      await oneNotice(page);
      await expect(notice(page)).toContainText("couldn't be loaded");
      expect(await where(page)).toEqual(before);
      mend();
      await notice(page).getByRole("button", { name: "Retry" }).click();
      await expect.poll(async () => (await where(page)).index).toBe(8);
      await expect(notice(page)).toBeHidden();
      expect((await where(page)).label).toBe("版權頁");

      // By the scrubber.
      await goTo(page, 0);
      await expect.poll(async () => (await where(page)).index).toBe(0);
      await page.waitForTimeout(300);
      const start = await where(page);
      expect(await available(page, 6)).toBe(false);
      mend = gate.fail("c-007");
      const scrubber = page
        .getByRole("toolbar", { name: "Reading controls" })
        .locator("input[type=range]");
      if (!(await scrubber.isVisible())) {
        const cdp = await context.newCDPSession(page);
        await touchTap(cdp, { x: 195, y: 420 }, 60);
      }
      await scrubber.evaluate((el) => {
        const input = el as HTMLInputElement;
        input.value = "80";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await expect(notice(page)).toContainText("couldn't be loaded");
      expect(await where(page)).toEqual(start);
      mend();
      await notice(page).getByRole("button", { name: "Retry" }).click();
      await expect.poll(async () => (await where(page)).index).toBe(6);
      expect((await where(page)).fraction).toBeGreaterThan(0.3);

      // By a page turn; put away, the notice stays away.
      expect(await available(page, 4)).toBe(false);
      mend = gate.fail("c-005");
      await goTo(page, { index: 3, fraction: 1 });
      await expect.poll(async () => (await where(page)).index).toBe(3);
      await expect.poll(() => atRest(page)).toBe(true);
      await page.waitForTimeout(400);
      const edge = await where(page);
      await page.keyboard.press("PageDown");
      await expect(notice(page)).toContainText("couldn't be loaded");
      await expect.poll(() => atRest(page)).toBe(true);
      expect(await where(page)).toEqual(edge);
      await notice(page).getByRole("button", { name: "Close" }).click();
      await expect(notice(page)).toBeHidden();
      mend();
      await page.keyboard.press("PageDown");
      await expect.poll(async () => (await where(page)).index).toBe(4);

      await page.waitForTimeout(2600);
      expectSound(seen);
    });

    test("a picture that fails to load does not fail its chapter", async ({
      page,
    }) => {
      const { seen, gate } = await open(page, turn);
      gate.fail("images/");
      await goTo(page, 4);
      await expect.poll(async () => (await where(page)).index).toBe(4);
      const doc = await page.evaluate(() => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        const img = doc.querySelector("img")!;
        return {
          text: doc.body.textContent!.includes("渡客之章第1段"),
          picture: img.complete && img.naturalWidth > 0,
        };
      });
      expect(doc).toEqual({ text: true, picture: false });
      expect(await notice(page).count()).toBe(0);
      expect((await where(page)).label).toBe("渡客");
      expectSound(seen);
    });
  });
}

test("offline, a seek into a chapter that is not loaded asks for it, once, and is answered at once", async ({
  page,
  context,
}) => {
  const { seen } = await open(page, "fade");
  const before = await where(page);
  expect(await available(page, 7)).toBe(false);
  await context.setOffline(true);
  const asked = requests(page, "c-008");

  const scrubber = page
    .getByRole("toolbar", { name: "Reading controls" })
    .locator("input[type=range]");
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  await scrubber.evaluate((el) => {
    const input = el as HTMLInputElement;
    input.value = "90";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await expect(notice(page)).toContainText("offline");
  expect(await where(page)).toEqual(before);
  await page.waitForTimeout(600);
  expect(asked.length).toBe(1);

  // The connection returns: the seek is made.
  await context.setOffline(false);
  await expect
    .poll(async () => (await where(page)).index, { timeout: 15_000 })
    .toBe(7);
  await expect(notice(page)).toBeHidden();
  expectSound(seen);
});

const toasts = (page: Page) => page.locator(".toast-position [role=status]");
const readingBar = (page: Page) =>
  page.getByRole("toolbar", { name: "Reading controls" });

async function rect(locator: ReturnType<Page["locator"]>) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return { top: box!.y, bottom: box!.y + box!.height, ...box! };
}

test("the notice is a toast: clear of the bottom bar, beside a save that fails, taken down by Retry and back when that fails; the connection returning while it shows opens the chapter", async ({
  page,
  context,
}) => {
  const { seen, gate } = await open(page, "fade");
  const before = await where(page);
  const viewport = page.viewportSize()!;
  const cdp = await context.newCDPSession(page);
  const asked = requests(page, "c-009");

  let mend = gate.fail("c-009");
  await openToc(page, context);
  await tocDialog(page).getByRole("button", { name: "版權頁" }).click();
  await expect(notice(page)).toContainText("couldn't be loaded");
  await expect(tocDialog(page)).toBeHidden();
  // One toast among the toasts, with what a toast has.
  await expect(toasts(page)).toHaveCount(1);
  await expect(notice(page)).toHaveAttribute("role", "status");
  await expect(notice(page).getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(notice(page).getByRole("button", { name: "Close" })).toBeVisible();

  // No bar: clear of the foot of the screen (and the home indicator).
  await expect(readingBar(page)).toBeHidden();
  await page.waitForTimeout(300);
  let box = await rect(notice(page));
  expect(viewport.height - box.bottom).toBeGreaterThanOrEqual(16);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);

  // The bar comes up: the toast is above it, not over its buttons.
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  await expect(readingBar(page)).toBeVisible();
  await expect
    .poll(async () => {
      const bar = await rect(readingBar(page));
      return bar.top - (await rect(notice(page))).bottom;
    })
    .toBeGreaterThanOrEqual(8);

  // A save that does not get through says so itself, beside it.
  await page.route("**/api/books/*/highlights", (route) =>
    route.request().method() === "POST" ? route.abort() : route.continue(),
  );
  const refused = page.waitForEvent("requestfailed", (r) =>
    r.url().endsWith("/highlights"),
  );
  const pt = await pointOnWord(page, "啟航之章第1段", 0);
  await touchTap(cdp, pt!, 900);
  await page
    .getByTestId("highlight-menu")
    .getByTitle("Highlight", { exact: true })
    .click();
  await refused;
  await expect(
    toasts(page).filter({ hasText: "Cannot reach the server" }),
  ).toBeVisible();
  await expect(notice(page)).toBeVisible();
  await expect(toasts(page)).toHaveCount(2);
  await page.unroute("**/api/books/*/highlights");
  expect(await marks(page)).toHaveLength(0);
  expect(await where(page)).toEqual(before);

  // Retry, with the request out: the toast is gone, the reader's
  // spinner says something is on its way, nobody has moved.
  mend();
  const release = gate.hold("c-009");
  const tries = asked.length;
  await notice(page).getByRole("button", { name: "Retry" }).click();
  await expect(notice(page)).toHaveCount(0);
  await expect(spinner(page)).toBeVisible();
  await expect.poll(() => asked.length).toBe(tries + 1);
  expect(await where(page)).toEqual(before);

  // It fails: the toast is back.
  mend = gate.fail("c-009");
  release();
  await expect(notice(page)).toContainText("couldn't be loaded");
  await expect(spinner(page)).toHaveCount(0);
  expect(await where(page)).toEqual(before);

  // Offline it is still tried, and the toast that comes back says why.
  await context.setOffline(true);
  await notice(page).getByRole("button", { name: "Retry" }).click();
  await expect.poll(() => asked.length).toBe(tries + 2);
  await oneNotice(page);
  await expect(notice(page)).toContainText("offline");
  expect(await where(page)).toEqual(before);

  // The connection returns while it shows: tried unprompted, the
  // chapter opens and the toast goes.
  mend();
  await context.setOffline(false);
  await expect
    .poll(async () => (await where(page)).index, { timeout: 15_000 })
    .toBe(8);
  await expect(notice(page)).toHaveCount(0);
  expect((await where(page)).label).toBe("版權頁");
  expectSound(seen);
});

test("the notice leaves by itself, or is closed, and the failure with it: the connection returning afterwards moves nobody", async ({
  page,
  context,
}) => {
  const { seen } = await open(page, "fade");
  const before = await where(page);
  const asked = requests(page, "c-009");
  await context.setOffline(true);
  await openToc(page, context);
  await entry(page, "版權頁").click();
  await expect(notice(page)).toContainText("offline");
  const shown = Date.now();
  await expect(entry(page, "版權頁")).not.toHaveAttribute("data-toc-trying");
  await tocDialog(page).getByRole("button", { name: "Close" }).click();
  // Nobody touches it (the pointer is parked away from it): there well
  // into its time, gone soon after.
  await page.mouse.move(5, 5);
  await page.waitForTimeout(Math.max(0, 12_000 - (Date.now() - shown)));
  await expect(notice(page)).toBeVisible();
  await expect(notice(page)).toHaveCount(0, { timeout: 6_000 });
  expect(Date.now() - shown).toBeGreaterThan(14_000);
  expect(asked.length).toBe(1);

  await context.setOffline(false);
  await page.waitForTimeout(2500);
  expect(await where(page)).toEqual(before);
  expect(asked.length).toBe(1);
  expect(await toasts(page).count()).toBe(0);

  // Closed by hand: the same.
  await context.setOffline(true);
  await openToc(page, context);
  await entry(page, "版權頁").click();
  await expect(notice(page)).toContainText("offline");
  await expect(entry(page, "版權頁")).not.toHaveAttribute("data-toc-trying");
  await tocDialog(page).getByRole("button", { name: "Close" }).click();
  await notice(page).getByRole("button", { name: "Close" }).click();
  await expect(notice(page)).toHaveCount(0);
  expect(asked.length).toBe(2);
  await context.setOffline(false);
  await page.waitForTimeout(2500);
  expect(await where(page)).toEqual(before);
  expect(asked.length).toBe(2);

  // Asked for by the reader, it opens.
  await openToc(page, context);
  await entry(page, "版權頁").click();
  await expect.poll(async () => (await where(page)).index).toBe(8);
  expectSound(seen);
});

test("offline, a marked entry being asked for waits and takes no second tap; when the chapter does not come the list stays, the notice says so, and Retry asks for that chapter", async ({
  page,
  context,
}) => {
  const { seen, gate } = await open(page, "fade");
  const before = await where(page);
  await context.setOffline(true);
  const last = requests(page, "c-009");
  const eighth = requests(page, "c-008");
  await openToc(page, context);
  const row = entry(page, "版權頁");
  await expect(row).toHaveAttribute("data-toc-unavailable");
  const marked = await rect(row);

  // The request is out: the entry says it is being tried, where its mark
  // was and without moving, and a second tap asks nothing more.
  const release = gate.hold("c-009");
  await row.click();
  await expect(row).toHaveAttribute("data-toc-trying");
  await expect(row).toHaveAttribute("aria-busy", "true");
  await expect(row.locator("svg")).toHaveCount(1);
  await expect(row.locator("svg")).toHaveClass(/animate-spin/);
  expect(await rect(row)).toEqual(marked);
  await expect.poll(() => last.length).toBe(1);
  await row.click();
  await page.waitForTimeout(700);
  expect(last.length).toBe(1);
  await expect(row).toHaveAttribute("data-toc-trying");
  // Still marked, the list still open, nothing said yet, nobody moved.
  await expect(row).toHaveAttribute("data-toc-unavailable");
  await expect(tocDialog(page)).toBeVisible();
  expect(await notice(page).count()).toBe(0);
  expect(await where(page)).toEqual(before);

  // It does not come: marked as before, the list open, the notice up.
  release();
  await expect(row).not.toHaveAttribute("data-toc-trying");
  await expect(row).not.toHaveAttribute("aria-busy");
  await expect(row).toHaveAttribute("data-toc-unavailable");
  await expect(row.locator("svg")).not.toHaveClass(/animate-spin/);
  expect(await rect(row)).toEqual(marked);
  await expect(notice(page)).toContainText("offline");
  await expect(notice(page)).toHaveAttribute("data-repeats", "0");
  await expect(tocDialog(page)).toBeVisible();
  expect(await where(page)).toEqual(before);
  expect(last.length).toBe(1);

  // Another marked entry, the notice already up: asked for, and the
  // same toast says once more that it did not come.
  const other = entry(page, "歸港");
  const retry = notice(page).getByRole("button", { name: "Retry" });
  const releaseOther = gate.hold("c-008");
  await other.click();
  await expect(other).toHaveAttribute("data-toc-trying");
  await expect(row).not.toHaveAttribute("data-toc-trying");
  await expect.poll(() => eighth.length).toBe(1);
  await expect(notice(page)).toHaveAttribute("data-repeats", "0");
  releaseOther();
  await expect(other).not.toHaveAttribute("data-toc-trying");
  await expect(notice(page)).toHaveAttribute("data-repeats", "1");
  await expect(toasts(page)).toHaveCount(1);
  await expect(tocDialog(page)).toBeVisible();
  expect(await where(page)).toEqual(before);

  // Retry is for the chapter asked for last — that one, not the first.
  // It takes the toast down; the attempt failing brings one back.
  await retry.click();
  await expect.poll(() => eighth.length).toBe(2);
  await oneNotice(page);
  await expect(notice(page)).toHaveAttribute("data-repeats", "0");
  expect(last.length).toBe(1);
  await expect(tocDialog(page)).toBeVisible();
  expect(await where(page)).toEqual(before);

  // And when it is there to be had (still offline), Retry opens it.
  const stop = await serveOffline(page, "c-008");
  await retry.click();
  await expect.poll(async () => (await where(page)).index).toBe(7);
  expect(await page.evaluate(() => navigator.onLine)).toBe(false);
  await expect(notice(page)).toHaveCount(0);
  await expect(tocDialog(page)).toBeHidden();
  expect((await where(page)).label).toBe("歸港");
  expect(eighth.length).toBe(3);
  await stop();
  expectSound(seen);
});

test("offline, a marked entry whose chapter is there to be had opens: the reader goes there, the list closes, nothing is said, and the entry is no longer marked", async ({
  page,
  context,
}) => {
  const { seen } = await open(page, "fade");
  expect(await available(page, 8)).toBe(false);
  await context.setOffline(true);
  const asked = requests(page, "c-009");
  const stop = await serveOffline(page, "c-009");
  await openToc(page, context);
  await expect(entry(page, "版權頁")).toHaveAttribute("data-toc-unavailable");

  await entry(page, "版權頁").click();
  await expect.poll(async () => (await where(page)).index).toBe(8);
  await expect(tocDialog(page)).toBeHidden();
  expect(await notice(page).count()).toBe(0);
  expect(await page.evaluate(() => navigator.onLine)).toBe(false);
  expect(await where(page)).toMatchObject({ label: "版權頁", live: 8 });
  expect(asked.length).toBe(1);
  await stop();

  // Still offline: that chapter is in memory now, the others are not.
  await openToc(page, context);
  await expect(entry(page, "版權頁")).not.toHaveAttribute(
    "data-toc-unavailable",
  );
  await expect(entry(page, "版權頁").locator("svg")).toHaveCount(0);
  await expect(entry(page, "夜泊")).toHaveAttribute("data-toc-unavailable");
  await page.waitForTimeout(600);
  expect(await notice(page).count()).toBe(0);
  expectSound(seen);
});

test("a retry made just before the connection returns is made again with it", async ({
  page,
  context,
}) => {
  const { seen } = await open(page, "fade");
  await context.setOffline(true);
  await openToc(page, context);
  await entry(page, "版權頁").click();
  await expect(notice(page)).toContainText("offline");
  await expect(entry(page, "版權頁")).not.toHaveAttribute("data-toc-trying");
  // The attempt made offline is still out when the connection comes
  // back, and then fails: the chapter is asked for once more.
  let first = true;
  let letGo: () => void = () => {};
  const heldBack = new Promise<void>((resolve) => (letGo = resolve));
  await page.route(CONTENT, async (route: Route) => {
    const url = decodeURIComponent(route.request().url());
    if (!url.includes("c-009") || !first) return route.fallback();
    first = false;
    await heldBack;
    await route.abort();
  });
  await notice(page).getByRole("button", { name: "Retry" }).click();
  await expect(notice(page)).toHaveCount(0);
  await expect.poll(() => first).toBe(false);
  await context.setOffline(false);
  await page.waitForTimeout(300);
  await expect(notice(page)).toHaveCount(0);
  expect((await where(page)).index).toBe(0);
  letGo();
  await expect
    .poll(async () => (await where(page)).index, { timeout: 15_000 })
    .toBe(8);
  await expect(notice(page)).toBeHidden();
  await expect(tocDialog(page)).toBeHidden();
  expectSound(seen);
});

test.describe("on a desktop", () => {
  const { defaultBrowserType: _chromium, ...desktop } =
    devices["Desktop Chrome"];
  test.use(desktop);

  test("the notice is at the foot of the window, and Retry after a failed page turn opens the chapter", async ({
    page,
  }) => {
    const seen = watch(page);
    const g = await gate(page);
    const bookId = await seedFixture(page.request, NINE_CHAPTERS_BOOK);
    await resetProgress(page.request, bookId);
    await openBook(page, bookId, { turn: "fade" }, NINE_CHAPTERS_BOOK);
    await expect.poll(() => available(page, 3)).toBe(true);
    await expect(readingBar(page)).toBeHidden();
    const viewport = page.viewportSize()!;

    expect(await available(page, 4)).toBe(false);
    const mend = g.fail("c-005");
    await goTo(page, { index: 3, fraction: 1 });
    await expect
      .poll(() =>
        page.evaluate(() => window.__beepubReaderNG.core.lastLocation.index),
      )
      .toBe(3);
    await page.waitForTimeout(400);
    await page.keyboard.press("PageDown");
    await expect(notice(page)).toContainText("couldn't be loaded");

    // (The toast flies in: read its place once it has settled.)
    await expect
      .poll(
        async () => viewport.height - (await rect(notice(page))).bottom,
      )
      .toBeGreaterThanOrEqual(8);
    const box = await rect(notice(page));
    expect(viewport.height - box.bottom).toBeLessThanOrEqual(16);
    const centre = box.x + box.width / 2;
    expect(Math.abs(centre - viewport.width / 2)).toBeLessThan(2);

    const asked = requests(page, "c-005");
    const retry = notice(page).getByRole("button", { name: "Retry" });
    await retry.click();
    await expect.poll(() => asked.length).toBe(1);
    await oneNotice(page);
    mend();
    await retry.click();
    await expect
      .poll(() =>
        page.evaluate(() => window.__beepubReaderNG.core.lastLocation.index),
      )
      .toBe(4);
    await expect(notice(page)).toBeHidden();
    expect(seen.errors).toEqual([]);
  });
});
