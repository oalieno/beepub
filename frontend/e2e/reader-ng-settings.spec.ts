import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  TOUCH_BOOK,
  VERTICAL_BOOK,
  iphone,
  openBook,
  resetProgress,
  seedFixture,
  type Fixture,
} from "./ng-helpers";

/**
 * reader-ng settings sheet (G2 ③): the sheet drives the engine through
 * BookReader's boundary layer and persists under the reader-* keys.
 *
 * The two gutters are screen-space — top/bottom and left/right — in
 * every writing mode. Underneath, the paginator's gap is inline padding
 * and its margin the block outer margin, so the mapping flips for
 * vertical text; these tests only look at where the text ends up.
 */

test.use({ storageState: ADMIN_STATE });

/** Extents of the visible text, relative to the paginator element. */
async function textBox(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const frame = doc.defaultView!.frameElement as HTMLIFrameElement;
    const fb = frame.getBoundingClientRect();
    const host = (core.paginator as HTMLElement).getBoundingClientRect();
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    // Nearest text to each edge: min distance from the host's top, left
    // and right edges.
    let top = Infinity;
    let left = Infinity;
    let right = Infinity;
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (!n.textContent?.trim()) continue;
      const rg = doc.createRange();
      rg.selectNodeContents(n);
      for (const r of rg.getClientRects()) {
        if (r.width <= 0 || r.height <= 0) continue;
        const t = r.top + fb.top;
        const l = r.left + fb.left;
        const rr = r.right + fb.left;
        // Only rects on screen: the section is one long strip of pages.
        if (t < host.top - 1 || t > host.bottom) continue;
        if (rr < host.left + 1 || l > host.right - 1) continue;
        top = Math.min(top, t - host.top);
        left = Math.min(left, l - host.left);
        right = Math.min(right, host.right - rr);
      }
    }
    return { top, left, right };
  });
}

async function bodyStyle(page: Page) {
  return page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const cs = getComputedStyle(doc.body);
    return { fontSize: cs.fontSize, letterSpacing: cs.letterSpacing };
  });
}

function openSheet(page: Page) {
  return page.getByRole("button", { name: "Reader settings" }).click();
}

async function waitForBook(page: Page, fixture: Fixture) {
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await expect
    .poll(() =>
      page.evaluate((text) => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        return doc.body?.textContent?.includes(text) ?? false;
      }, fixture.readyText),
    )
    .toBe(true);
}

test.afterEach(async ({ page }) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await resetProgress(page.request, bookId);
});

test("font size and letter spacing apply through the sheet and persist", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId);
  expect((await bodyStyle(page)).fontSize).toBe("18px");

  await openSheet(page);
  await page.getByRole("button", { name: "Increase font size" }).click();
  await expect(page.getByTestId("setting-font-size")).toHaveText("20px");
  await page.getByRole("button", { name: "Increase Letter spacing" }).click();
  await page.getByRole("button", { name: "Increase Letter spacing" }).click();
  await expect(page.getByTestId("setting-letter-spacing")).toHaveText("1px");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await expect
    .poll(() => bodyStyle(page))
    .toEqual({
      fontSize: "20px",
      letterSpacing: "1px",
    });
  expect(
    await page.evaluate(() => [
      localStorage.getItem("reader-size"),
      localStorage.getItem("reader-letter-spacing"),
    ]),
  ).toEqual(["20", "1"]);

  // A plain open (no query overrides) reads the stored values back.
  await page.goto(`/books/${bookId}/read`);
  await waitForBook(page, TOUCH_BOOK);
  await expect
    .poll(() => bodyStyle(page))
    .toEqual({
      fontSize: "20px",
      letterSpacing: "1px",
    });
});

test("the old single margin seeds both gutters", async ({ page }) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await page.addInitScript(() => {
    localStorage.setItem("reader-margin", "56");
    localStorage.removeItem("reader-margin-x");
    localStorage.removeItem("reader-margin-y");
  });
  await page.goto(`/books/${bookId}/read`);
  await waitForBook(page, TOUCH_BOOK);
  await openSheet(page);
  await expect(page.getByTestId("setting-margin-x")).toHaveText("56px");
  await expect(page.getByTestId("setting-margin-y")).toHaveText("56px");
  // Stepping writes the split key only; the legacy key stays for the
  // other reader.
  await page.getByRole("button", { name: "Increase Side margins" }).click();
  await expect(page.getByTestId("setting-margin-x")).toHaveText("64px");
  expect(
    await page.evaluate(() => [
      localStorage.getItem("reader-margin-x"),
      localStorage.getItem("reader-margin-y"),
      localStorage.getItem("reader-margin"),
    ]),
  ).toEqual(["64", null, "56"]);
});

test("theme and page-turn mode persist", async ({ page }) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  await openBook(page, bookId);
  await openSheet(page);
  await page.getByRole("button", { name: "Dark", exact: true }).click();
  await expect(page.locator(".reader-dark")).toHaveCount(1);
  await page.getByRole("button", { name: "Slide" }).click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        window.__beepubReaderNG.paginator.hasAttribute("animated"),
      ),
    )
    .toBe(true);
  expect(
    await page.evaluate(() => [
      localStorage.getItem("reader-dark"),
      localStorage.getItem("reader-page-turn"),
    ]),
  ).toEqual(["1", "slide"]);
});

test.describe("gutters are screen-space in both writing modes", () => {
  // A phone-width viewport: on a wide screen the text measure caps at
  // 720px and the side gutters grow past the setting.
  test.use({ ...iphone });

  test("horizontal: left/right ← mx, top/bottom ← my", async ({ page }) => {
    const bookId = await seedFixture(page.request, TOUCH_BOOK);
    await openBook(page, bookId, { mx: "16", my: "16" });
    const base = await textBox(page);
    expect(base.left).toBeGreaterThan(10);

    await openBook(page, bookId, { mx: "64", my: "16" });
    const wider = await textBox(page);
    expect(Math.abs(wider.left - base.left - 48)).toBeLessThanOrEqual(2);
    expect(Math.abs(wider.top - base.top)).toBeLessThanOrEqual(2);

    await openBook(page, bookId, { mx: "16", my: "64" });
    const taller = await textBox(page);
    expect(Math.abs(taller.top - base.top - 48)).toBeLessThanOrEqual(2);
    expect(Math.abs(taller.left - base.left)).toBeLessThanOrEqual(2);
  });

  test("vertical: left/right ← mx, top/bottom ← my", async ({ page }) => {
    const bookId = await seedFixture(page.request, VERTICAL_BOOK);
    await resetProgress(page.request, bookId);
    const open = (mx: string, my: string) =>
      openBook(page, bookId, { mx, my, font: "sans" }, VERTICAL_BOOK);
    await open("16", "16");
    expect(
      await page.evaluate(() => window.__beepubReaderNG.core.vertical),
    ).toBe(true);
    const base = await textBox(page);

    // Vertical-rl starts at the right edge: the side gutter shows there.
    await open("64", "16");
    const wider = await textBox(page);
    expect(Math.abs(wider.right - base.right - 48)).toBeLessThanOrEqual(2);
    expect(Math.abs(wider.top - base.top)).toBeLessThanOrEqual(2);

    await open("16", "64");
    const taller = await textBox(page);
    expect(Math.abs(taller.top - base.top - 48)).toBeLessThanOrEqual(2);
    expect(Math.abs(taller.right - base.right)).toBeLessThanOrEqual(2);
  });
});
