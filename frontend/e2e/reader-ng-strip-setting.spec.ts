import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  LONG_CHAPTERS_BOOK,
  iphone,
  openBook,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * The scroll mode as a setting: "Scroll" beside the page-turn modes in
 * the reader's settings, kept like them, taking the reader in place to
 * the strip and back — and, while a book is scrolled, nothing in the
 * chrome that would turn a page.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(120_000);

const place = (page: Page) =>
  page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return {
      index: l.index as number,
      cfi: l.startCfi as string,
      sized: l.size != null,
    };
  });

const scrolled = (page: Page) =>
  page.evaluate(() => !!window.__beepubReaderNG?.core?.strip);

const stored = (page: Page) =>
  page.evaluate(() => localStorage.getItem("reader-page-turn"));

/** Whether the text at `cfi` is on the screen now, paged or scrolled. */
function onScreen(page: Page, cfi: string) {
  return page.evaluate((cfi) => {
    const core = window.__beepubReaderNG.core;
    const l = core.lastLocation;
    const target = core.resolve(cfi);
    const content = (
      core.getContents() as { index: number; doc: Document }[]
    ).find((c) => c.index === target.index);
    if (!content || !l?.range) return false;
    const anchor = target.anchor(content.doc) as Range;
    return (l.range as Range).isPointInRange(
      anchor.startContainer,
      anchor.startOffset,
    );
  }, cfi);
}

async function waitForReader(page: Page) {
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await page.waitForTimeout(500);
}

test("Scroll is chosen in the settings: the reader goes to the strip where it was, the choice is kept, and a page-turn mode brings the pages back", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  // (No ?turn: the stored preference, a new reader's fade.)
  await openBook(page, bookId, { turn: "" }, LONG_CHAPTERS_BOOK);
  expect(await scrolled(page)).toBe(false);
  await page.evaluate(
    () =>
      window.__beepubReaderNG.core.goTo({
        index: 1,
        fraction: 0.3,
      }) as Promise<unknown>,
  );
  await expect.poll(async () => (await place(page)).index).toBe(1);
  const paged = await place(page);
  // In pages the chrome turns them.
  await expect(page.getByRole("button", { name: "Next page" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Previous page" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Reader settings" }).click();
  const row = page.getByTestId("setting-page-turn");
  await expect(row.getByRole("button")).toHaveText([
    "Fast fade",
    "Slide",
    "Scroll",
  ]);
  await row.getByRole("button", { name: "Scroll" }).click();
  await expect.poll(() => scrolled(page)).toBe(true);
  await expect(page.getByTestId("scroll-strip")).toBeVisible();
  await expect.poll(() => onScreen(page, paged.cfi)).toBe(true);
  expect((await place(page)).index).toBe(1);
  expect(await stored(page)).toBe("scroll");
  await page.keyboard.press("Escape");

  // Nothing of the prototype is on the page, and nothing turns a page.
  await expect(page.getByTestId("scroll-strip-readout")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Next page" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Previous page" })).toHaveCount(
    0,
  );
  // The gesture help says what is true of a scrolled book: no sides to
  // tap for a page, no swipe or key that turns one.
  await page.getByTitle("Gestures & shortcuts").click();
  const help = page.getByRole("dialog", { name: "Reading gestures" });
  await expect(help).toBeVisible();
  await expect(help).not.toContainText("Next page");
  await expect(help).not.toContainText("turn pages");
  await expect(help).toContainText("Got it");
  await help.getByRole("button", { name: "Got it" }).click();
  await expect(help).toBeHidden();

  // Opened again with no override: still scrolled, at the same place.
  const read = await place(page);
  await expect
    .poll(async () => {
      const res = await request.get(`/api/books/${bookId}/progress`);
      return (await res.json()).cfi as string;
    })
    .toBe(read.cfi);
  await page.goto(`/books/${bookId}/read?size=18&lh=1.8&mx=24&my=48`);
  await waitForReader(page);
  expect(await scrolled(page)).toBe(true);
  expect((await place(page)).cfi).toBe(read.cfi);
  await expect(page.getByRole("button", { name: "Next page" })).toHaveCount(0);

  // A page-turn mode: the pages again, at the same place.
  await page.getByRole("button", { name: "Reader settings" }).click();
  await page
    .getByTestId("setting-page-turn")
    .getByRole("button", { name: "Fast fade" })
    .click();
  await expect.poll(() => scrolled(page)).toBe(false);
  await expect(page.getByTestId("scroll-strip")).toHaveCount(0);
  await expect.poll(async () => (await place(page)).sized).toBe(true);
  await expect.poll(() => onScreen(page, read.cfi)).toBe(true);
  expect(await stored(page)).toBe("fade");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Next page" })).toBeVisible();
  await page.getByTitle("Gestures & shortcuts").click();
  await expect(help).toContainText("Next page");
  await expect(help).toContainText("turn pages");
});

test("the option is named in Traditional Chinese", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await page.addInitScript(() =>
    localStorage.setItem("PARAGLIDE_LOCALE", "zh-Hant"),
  );
  await openBook(page, bookId, { turn: "" }, LONG_CHAPTERS_BOOK);
  await page.getByRole("button", { name: "閱讀器設定" }).click();
  const row = page.getByTestId("setting-page-turn");
  await expect(row.getByRole("button")).toHaveText([
    "快速淡化",
    "滑動",
    "捲動",
  ]);
  await row.getByRole("button", { name: "捲動" }).click();
  await expect.poll(() => scrolled(page)).toBe(true);
});

test.describe("on a phone", () => {
  test.use({ ...iphone });

  test("the bar's page buttons are there in pages and gone while the book is scrolled", async ({
    page,
    request,
  }) => {
    const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
    await resetProgress(request, bookId);
    const bar = page.getByRole("toolbar", { name: "Reading controls" });
    const showBar = async () => {
      if (await bar.isVisible()) return;
      const view = page.viewportSize()!;
      await page.touchscreen.tap(view.width / 2, view.height / 2);
      await expect(bar).toBeVisible();
    };

    await openBook(page, bookId, { turn: "scroll" }, LONG_CHAPTERS_BOOK);
    expect(await scrolled(page)).toBe(true);
    // A tap anywhere — a side of the screen too — is the chrome's.
    await page.touchscreen.tap(20, page.viewportSize()!.height / 2);
    await expect(bar).toBeVisible();
    await expect(bar.getByRole("button", { name: "Next page" })).toHaveCount(0);
    await expect(
      bar.getByRole("button", { name: "Previous page" }),
    ).toHaveCount(0);
    await expect(bar.getByRole("slider")).toBeVisible();

    await openBook(page, bookId, { turn: "fade" }, LONG_CHAPTERS_BOOK);
    expect(await scrolled(page)).toBe(false);
    await showBar();
    await expect(bar.getByRole("button", { name: "Next page" })).toBeVisible();
    await expect(
      bar.getByRole("button", { name: "Previous page" }),
    ).toBeVisible();
  });
});
