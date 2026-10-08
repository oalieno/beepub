import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  CHAPTER_ANCHORS_BOOK,
  openBook,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * reader-ng: the chapter named in the chrome. A chapter's first page is
 * already that chapter — even when its TOC anchor is an empty element a
 * node or two after the place the page's range starts — and turning into
 * it never names an earlier chapter on the way.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(90_000);

const label = (page: Page) =>
  page.locator('[data-testid="reader-chapter"]:visible');

/** Every chapter name the chrome shows from now on, in order, starting
 *  with the one it shows now. */
async function recordLabels(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __labels: string[] };
    w.__labels = [];
    const read = () => {
      const el = document.querySelector('[data-testid="reader-chapter"]');
      const text = el?.textContent?.trim() ?? "";
      if (text && w.__labels[w.__labels.length - 1] !== text)
        w.__labels.push(text);
    };
    read();
    new MutationObserver(read).observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
    });
  });
}

test("a chapter's first page names that chapter, with no detour on the way in", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await resetProgress(page.request, bookId);
  await openBook(page, bookId, {}, CHAPTER_ANCHORS_BOOK);
  await expect(label(page)).toHaveText("第一話「潮汐」");

  // To the last page of the second chapter, then one turn into the third.
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
  await expect(label(page)).toHaveText("第二話「燈芯」");
  const next = page.getByRole("button", { name: "Next page" });
  const index = () =>
    page.evaluate(() => window.__beepubReaderNG.core.lastLocation.index);
  const atLastPage = () =>
    page.evaluate(() => {
      const l = window.__beepubReaderNG.core.lastLocation;
      return l.fraction + l.size >= 1 - 1e-6;
    });
  for (let i = 0; i < 40 && !(await atLastPage()); i++) {
    await next.click();
    await page.waitForTimeout(300);
  }
  expect(await atLastPage()).toBe(true);
  expect(await index()).toBe(1);
  await expect(label(page)).toHaveText("第二話「燈芯」");

  await recordLabels(page);
  await next.click();
  await expect.poll(index).toBe(2);
  await page.waitForTimeout(600);
  expect(
    await page.evaluate(
      () => window.__beepubReaderNG.core.lastLocation.fraction,
    ),
  ).toBe(0);
  await expect(label(page)).toHaveText("第三話「霧笛」");
  expect(
    await page.evaluate(
      () => (window as unknown as { __labels: string[] }).__labels,
    ),
  ).toEqual(["第二話「燈芯」", "第三話「霧笛」"]);
});

test("in the slide mode the name changes as the slide lands, and back with the turn back", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await resetProgress(page.request, bookId);
  await openBook(page, bookId, { turn: "slide" }, CHAPTER_ANCHORS_BOOK);
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
  await expect(label(page)).toHaveText("第二話「燈芯」");
  const next = page.getByRole("button", { name: "Next page" });
  const where = () =>
    page.evaluate(() => {
      const { core, paginator } = window.__beepubReaderNG;
      const l = core.lastLocation;
      return {
        index: l.index as number,
        last: l.fraction + l.size >= 1 - 1e-6,
        first: l.fraction === 0,
        liveIndex: paginator.getContents()[0]?.index as number,
      };
    });
  // One turn at a time, each seen to have landed (the position changes
  // as the slide ends — not a fixed while after the tap).
  const fraction = () =>
    page.evaluate(
      () => window.__beepubReaderNG.core.lastLocation.fraction as number,
    );
  for (let i = 0; i < 40 && !(await where()).last; i++) {
    const before = await fraction();
    await next.click();
    await expect.poll(fraction).not.toBe(before);
  }
  expect(await where()).toMatchObject({ index: 1, last: true });
  // Both neighbouring pages rendered, as after a moment on the page.
  await expect
    .poll(() =>
      page.evaluate(() => {
        const { core } = window.__beepubReaderNG;
        return [1, -1].map(
          (dir) => core.ghostFor(dir)?.getContents()[0]?.index ?? null,
        );
      }),
    )
    .toEqual([2, 1]);
  await page.waitForTimeout(300);

  // Into the third chapter: named the moment the slide has landed,
  // while the live paginator is still in the second.
  await recordLabels(page);
  // (Where the live paginator is, taken in the page as the name changes:
  // asked from here it may have followed by the time the answer is back.)
  await label(page).evaluate((el) => {
    const w = window as unknown as { __liveAtRename?: number };
    delete w.__liveAtRename;
    const observer = new MutationObserver(() => {
      if (!el.textContent?.includes("霧笛")) return;
      w.__liveAtRename = window.__beepubReaderNG.paginator.getContents()[0]
        ?.index as number;
      observer.disconnect();
    });
    observer.observe(el, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  });
  await next.click();
  await expect(label(page)).toHaveText("第三話「霧笛」");
  expect(
    await page.evaluate(
      () => (window as unknown as { __liveAtRename?: number }).__liveAtRename,
    ),
  ).toBe(1);
  expect(await where()).toMatchObject({ index: 2, first: true });
  // The live paginator follows, and nothing changes for it.
  await expect.poll(async () => (await where()).liveIndex).toBe(2);
  await page.waitForTimeout(600);
  expect(await where()).toMatchObject({ index: 2, first: true });

  // And back: the second chapter again, as its last page lands.
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(label(page)).toHaveText("第二話「燈芯」");
  expect(await where()).toMatchObject({ index: 1, last: true });
  await expect.poll(async () => (await where()).liveIndex).toBe(1);
  await page.waitForTimeout(600);
  expect(
    await page.evaluate(
      () => (window as unknown as { __labels: string[] }).__labels,
    ),
  ).toEqual(["第二話「燈芯」", "第三話「霧笛」", "第二話「燈芯」"]);
});
