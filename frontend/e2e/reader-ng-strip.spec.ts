import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  NINE_CHAPTERS_BOOK,
  resetProgress,
  seedFixture,
  seedGesturesSeen,
} from "./ng-helpers";

/**
 * The scroll strip (prototype, ?turn=scroll): chapters on one canvas,
 * laid out from the chapter being read. The rule under test: a chapter
 * joining or leaving the strip never moves the text on screen, and the
 * scroll position is not written for it.
 */

test.use({ storageState: ADMIN_STATE });

interface Strip {
  open(target: { index: number }): Promise<void>;
  scroller: HTMLElement;
  chapters: { index: number; top: number; height: number }[];
  pinnedIndex: number | null;
  log: { what: string; index?: number }[];
}
declare global {
  interface Window {
    __beepubStrip: Strip;
  }
}

async function openStrip(page: Page, bookId: string, index: number) {
  await seedGesturesSeen(page);
  await page.goto(`/books/${bookId}/read?turn=scroll&size=18&lh=1.8`);
  await page.waitForFunction(() => !!window.__beepubStrip?.chapters.length);
  await page.evaluate((i) => window.__beepubStrip.open({ index: i }), index);
}

const state = (page: Page) =>
  page.evaluate(() => {
    const s = window.__beepubStrip;
    const frame = s.scroller.querySelector<HTMLElement>(
      `[data-index="${s.pinnedIndex}"]`,
    )!;
    return {
      scrollTop: s.scroller.scrollTop,
      pinned: s.pinnedIndex,
      // Where the read chapter stands on screen.
      screenTop: Math.round(frame.getBoundingClientRect().top),
      indices: s.chapters.map((c) => c.index),
      tops: s.chapters.map((c) => c.top),
      heights: s.chapters.map((c) => c.height),
      canvas: s.scroller.scrollHeight,
      log: s.log.map((l) => `${l.what}${l.index ?? ""}`),
    };
  });

test("a chapter joining above or below leaves the read text where it is", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 4);
  const before = await state(page);
  expect(before.pinned).toBe(4);
  // The chapter before joins (the one after is not needed yet: the
  // opened chapter is several screens long).
  await expect.poll(async () => (await state(page)).indices).toContain(3);
  const after = await state(page);
  expect(after.scrollTop).toBe(before.scrollTop);
  expect(after.screenTop).toBe(before.screenTop);
  // Stacked without gaps, in order.
  for (let i = 1; i < after.indices.length; i++)
    expect(after.tops[i]).toBe(after.tops[i - 1] + after.heights[i - 1]);
});

test.setTimeout(120_000);

test("scrolling back reaches the book's first chapter at the canvas's top, and forward its end", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 4);
  const box = (await page.getByTestId("scroll-strip").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  // Back, a screen at a time, until the first chapter is the read one.
  for (let i = 0; i < 400 && (await state(page)).pinned !== 0; i++) {
    await page.mouse.wheel(0, -box.height * 0.8);
    await page.waitForTimeout(60);
  }
  await expect.poll(async () => (await state(page)).pinned).toBe(0);
  // At rest the canvas starts at the first chapter: the browser stops there.
  await expect.poll(async () => (await state(page)).tops[0]).toBe(0);
  for (let i = 0; i < 40; i++) await page.mouse.wheel(0, -box.height);
  await expect.poll(async () => (await state(page)).scrollTop).toBe(0);
  const start = await state(page);
  expect(start.screenTop).toBe(Math.round(box.y));
  expect(start.log.some((l) => l.startsWith("rebased"))).toBe(true);

  // Forward to the end of the book.
  let last = -1;
  for (let i = 0; i < 2000; i++) {
    await page.mouse.wheel(0, box.height * 0.8);
    await page.waitForTimeout(40);
    const s = await state(page);
    if (s.pinned === 8 && s.scrollTop === last) break;
    last = s.scrollTop;
  }
  const end = await state(page);
  expect(end.pinned).toBe(8);
  const n = end.indices.length - 1;
  expect(end.indices[n]).toBe(8);
  // No blank screen after the last chapter.
  expect(end.canvas).toBe(end.tops[n] + end.heights[n]);
  expect(end.log.some((l) => l.startsWith("let go"))).toBe(true);
});
