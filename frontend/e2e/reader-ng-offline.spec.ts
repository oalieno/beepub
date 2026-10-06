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
 * contents marks the chapters that cannot be opened.
 *
 * The notice sits at the bottom of the screen, above the phone's bottom
 * bar while that shows and below any toast. Trying again is seen to be
 * tried: the button waits while the request is out, the notice stays if
 * it fails (and says so once more), and goes when the chapter is there.
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

const notice = (page: Page) => page.getByTestId("reader-load-notice");
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
    test("offline, a chapter picked from the table of contents that is not loaded: marked, refused with a notice, and the reader stays put; back online it opens", async ({
      page,
      context,
    }) => {
      const { seen } = await open(page, turn);
      expect(await available(page, 8)).toBe(false);
      const before = await where(page);
      expect(before).toMatchObject({ index: 0, label: "啟航", percent: "0%" });

      await context.setOffline(true);
      await openToc(page, context);
      const dialog = tocDialog(page);
      // What is in memory is not marked; what is not, is.
      for (const name of ["啟航", "霧號", "潮表", "燈語"])
        await expect(
          dialog.getByRole("button", { name, exact: true }),
        ).not.toHaveAttribute("aria-disabled", "true");
      for (const name of ["渡客", "夜泊", "修纜", "歸港", "版權頁"]) {
        const entry = dialog.getByRole("button", { name });
        await expect(entry).toHaveAttribute("aria-disabled", "true");
        await expect(entry).toHaveAttribute("title", /offline/i);
        await expect(entry.locator("svg")).toBeVisible();
      }

      // (Marked aria-disabled, and still answering a tap.)
      await dialog.getByRole("button", { name: "版權頁" }).click({ force: true });
      await expect(notice(page)).toContainText("offline");
      await expect(notice(page).getByRole("button", { name: "Retry" })).toBeVisible();
      // The list stays; the page behind it has not moved.
      await expect(dialog).toBeVisible();
      expect(await where(page)).toEqual(before);
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
      await dialog.getByRole("button", { name: "版權頁" }).click({ force: true });
      await expect(notice(page)).toBeVisible();
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

      await page.keyboard.press("PageDown");
      await expect(notice(page)).toContainText("offline");
      await expect.poll(() => atRest(page)).toBe(true);
      expect(await where(page)).toEqual(before);

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
      await expect(notice(page)).toBeVisible();
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

test("offline, a seek into a chapter that is not loaded is answered at once, without a request", async ({
  page,
  context,
}) => {
  const { seen } = await open(page, "fade");
  const before = await where(page);
  expect(await available(page, 7)).toBe(false);
  await context.setOffline(true);
  const asked: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/content/")) asked.push(r.url());
  });

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
  expect(asked).toEqual([]);

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

test("the notice sits at the bottom, above the bar and below a toast; Retry waits, stays when it fails and goes when the chapter is there", async ({
  page,
  context,
}) => {
  const { seen, gate, bookId } = await open(page, "fade");
  const existing: { id: string }[] = await (
    await page.request.get(`/api/books/${bookId}/highlights`)
  ).json();
  const before = await where(page);
  const viewport = page.viewportSize()!;
  const cdp = await context.newCDPSession(page);
  const asked: string[] = [];
  page.on("request", (r) => {
    if (decodeURIComponent(r.url()).includes("c-009")) asked.push(r.url());
  });

  let mend = gate.fail("c-009");
  await openToc(page, context);
  await tocDialog(page).getByRole("button", { name: "版權頁" }).click();
  await expect(notice(page)).toContainText("couldn't be loaded");
  await expect(tocDialog(page)).toBeHidden();

  // No bar: at the foot of the screen.
  await expect(readingBar(page)).toBeHidden();
  let box = await rect(notice(page));
  expect(viewport.height - box.bottom).toBeGreaterThanOrEqual(8);
  expect(viewport.height - box.bottom).toBeLessThanOrEqual(16);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);

  // The bar comes up: the notice is above it, not under it.
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  await expect(readingBar(page)).toBeVisible();
  await expect
    .poll(async () => {
      const bar = await rect(readingBar(page));
      return bar.top - (await rect(notice(page))).bottom;
    })
    .toBeGreaterThanOrEqual(8);
  box = await rect(notice(page));
  expect((await rect(readingBar(page))).top - box.bottom).toBeLessThanOrEqual(
    16,
  );

  try {
    // While it is up, "cannot reach the server" would say the same thing
    // again: a save that does not get through raises no toast.
    await page.route("**/api/books/*/highlights", (route) =>
      route.request().method() === "POST" ? route.abort() : route.continue(),
    );
    const refused = page.waitForEvent("requestfailed", (r) =>
      r.url().endsWith("/highlights"),
    );
    const pt = await pointOnWord(page, "啟航之章第1段", 0);
    await touchTap(cdp, pt!, 900);
    const menu = page.getByTestId("highlight-menu");
    await menu.getByTitle("Highlight", { exact: true }).click();
    await refused;
    await page.waitForTimeout(400);
    await expect(toasts(page)).toHaveCount(0);
    await expect(notice(page)).toBeVisible();
    await page.unroute("**/api/books/*/highlights");

    // A toast that does show stands above the notice, clear of it.
    await touchTap(cdp, pt!, 900);
    await menu.getByTitle("Highlight", { exact: true }).click();
    const toast = toasts(page).filter({ hasText: "Highlight saved" });
    await expect(toast).toBeVisible();
    await expect.poll(() => marks(page)).not.toHaveLength(0);
    // (The toast flies in: read its place once it has settled.)
    await expect
      .poll(async () => {
        const t = await rect(toast);
        return (await rect(notice(page))).top - t.bottom;
      })
      .toBeGreaterThanOrEqual(4);
    await toast.getByRole("button", { name: "Close" }).click();
    await expect(toasts(page)).toHaveCount(0);
  } finally {
    const now: { id: string }[] = await (
      await page.request.get(`/api/books/${bookId}/highlights`)
    ).json();
    for (const h of now)
      if (!existing.some((e) => e.id === h.id))
        await page.request.delete(`/api/books/${bookId}/highlights/${h.id}`);
  }
  await expect(notice(page)).toBeVisible();
  expect(await where(page)).toEqual(before);

  // Retry, with the request out: the button waits, the notice stays, and
  // the list the reader has open stays open.
  mend();
  const release = gate.hold("c-009");
  await openToc(page, context);
  const retry = notice(page).getByRole("button", { name: "Retry" });
  await expect(retry).toBeEnabled();
  await expect(retry).toHaveAttribute("aria-busy", "false");
  await retry.click();
  await expect(retry).toBeDisabled();
  await expect(retry).toHaveAttribute("aria-busy", "true");
  await expect(retry.locator("svg")).toBeVisible();
  await page.waitForTimeout(800);
  await expect(retry).toBeDisabled();
  await expect(notice(page)).toBeVisible();
  await expect(tocDialog(page)).toBeVisible();
  expect(await where(page)).toEqual(before);

  // It fails: the button is a button again, the notice is still there
  // and has said so.
  await expect(notice(page)).toHaveAttribute("data-failures", "0");
  mend = gate.fail("c-009");
  release();
  await expect(retry).toBeEnabled();
  await expect(retry).toHaveAttribute("aria-busy", "false");
  await expect(notice(page)).toHaveAttribute("data-failures", "1");
  await expect(notice(page)).toContainText("couldn't be loaded");
  await expect(tocDialog(page)).toBeVisible();
  expect(await where(page)).toEqual(before);

  // Offline it is still tried — and seen to be, though the answer comes
  // at once.
  await context.setOffline(true);
  await expect(notice(page)).toContainText("offline");
  const tries = asked.length;
  await retry.click();
  await expect(retry).toBeDisabled();
  await expect(retry).toBeEnabled();
  await expect(notice(page)).toHaveAttribute("data-failures", "2");
  expect(asked.length).toBeGreaterThan(tries);
  expect(await where(page)).toEqual(before);

  // The connection returns: tried unprompted, the chapter opens, and the
  // notice and the list are gone.
  mend();
  await context.setOffline(false);
  await expect
    .poll(async () => (await where(page)).index, { timeout: 15_000 })
    .toBe(8);
  await expect(notice(page)).toBeHidden();
  await expect(tocDialog(page)).toBeHidden();
  expect((await where(page)).label).toBe("版權頁");
  expectSound(seen);
});

test("a retry made just before the connection returns is made again with it", async ({
  page,
  context,
}) => {
  const { seen } = await open(page, "fade");
  await context.setOffline(true);
  await openToc(page, context);
  await tocDialog(page).getByRole("button", { name: "版權頁" }).click({ force: true });
  await expect(notice(page)).toContainText("offline");
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
  const retry = notice(page).getByRole("button", { name: "Retry" });
  await retry.click();
  await expect(retry).toBeDisabled();
  await expect.poll(() => first).toBe(false);
  await context.setOffline(false);
  await page.waitForTimeout(300);
  await expect(retry).toBeDisabled();
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

    const box = await rect(notice(page));
    expect(viewport.height - box.bottom).toBeGreaterThanOrEqual(8);
    expect(viewport.height - box.bottom).toBeLessThanOrEqual(16);
    const centre = box.x + box.width / 2;
    expect(Math.abs(centre - viewport.width / 2)).toBeLessThan(2);

    const retry = notice(page).getByRole("button", { name: "Retry" });
    await retry.click();
    await expect(notice(page)).toHaveAttribute("data-failures", "1");
    await expect(retry).toBeEnabled();
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
