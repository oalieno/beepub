import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

// Two chapters with a ~15:1 text-size ratio: chapter 1 owns ~94% of the
// weight, so weight-interpolated progress and scrubber seeks have a shape
// uniform section counting could not fake.
const CHAPTERS_FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-vertical-chapters-book.epub",
);

test.use({ storageState: ADMIN_STATE });

async function uploadChaptersBook(page: Page): Promise<{ id: string }> {
  const libraries = await (await page.request.get("/api/libraries")).json();
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "progress-chapters.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(CHAPTERS_FIXTURE),
      },
      library_id: libraries[0].id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  return uploaded.json();
}

/** The worker extracts text shortly after upload; weights ride the book
 *  detail. Until then the reader falls back to uniform weights, but the
 *  tests below want the real ones so the numbers are deterministic. */
async function waitForWeights(page: Page, bookId: string): Promise<number[]> {
  await expect
    .poll(
      async () => {
        const detail = await (
          await page.request.get(`/api/books/${bookId}`)
        ).json();
        return detail.section_weights;
      },
      { timeout: 30_000, message: "text extraction never produced weights" },
    )
    .not.toBeNull();
  const detail = await (await page.request.get(`/api/books/${bookId}`)).json();
  return detail.section_weights;
}

function progressLabel(page: Page) {
  // The desktop bottom bar's percentage readout.
  return page.locator("span", { hasText: /^\d+%$/ }).first();
}

async function readPercent(page: Page): Promise<number> {
  return parseInt((await progressLabel(page).textContent()) ?? "0", 10);
}

test("progress is visible immediately and moves with the weights", async ({
  page,
}) => {
  const book = await uploadChaptersBook(page);
  const weights = await waitForWeights(page, book.id);
  const positive = weights.filter((w: number) => w > 0);
  expect(positive.length).toBe(2);

  await page.goto(`/books/${book.id}/read`);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.getByText("甲章首段").first()).toBeVisible({
    timeout: 30_000,
  });

  // No locations generation to wait for: the percentage readout exists as
  // soon as the book is displayed.
  await expect(progressLabel(page)).toBeVisible({ timeout: 10_000 });
  const initial = await readPercent(page);

  // Degenerate-fragmentation guard (no CJK fonts → one giant page).
  const pages = await page.evaluate(() => {
    const reader = (window as any).__beepubReader;
    const loc = reader?.rendition?.currentLocation?.();
    return loc?.start?.displayed?.total ?? 0;
  });
  test.skip(pages < 3, "vertical fragmentation degenerate — CJK fonts missing");

  // rtl book: ArrowLeft pages forward. Progress must be monotone and
  // actually advance.
  let last = initial;
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press("ArrowLeft");
    await page.waitForTimeout(400);
    const now = await readPercent(page);
    expect(now).toBeGreaterThanOrEqual(last);
    last = now;
  }
  expect(last).toBeGreaterThan(initial);
});

test("scrubber seek maps through the weights into the right chapter", async ({
  page,
}) => {
  const book = await uploadChaptersBook(page);
  const weights = await waitForWeights(page, book.id);
  const total = weights.reduce((a: number, b: number) => a + b, 0);
  const lastIndex = weights.length - 1;
  let before = 0;
  for (let i = 0; i < lastIndex; i++) before += weights[i];
  const chapter2Start = Math.ceil((before / total) * 100);
  expect(chapter2Start).toBeGreaterThan(80); // the fixture's 15:1 shape

  await page.goto(`/books/${book.id}/read`);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.getByText("甲章首段").first()).toBeVisible({
    timeout: 30_000,
  });

  // The desktop progress bar is collapsible — the slider stays in the DOM
  // while folded, and this test cares about the weight mapping, not the
  // fold state. Dispatch the events directly.
  const scrubber = page.locator("input[type=range]").first();
  await expect(scrubber).toBeAttached({ timeout: 10_000 });
  const target = Math.min(99, chapter2Start + 2);
  await scrubber.evaluate((el, value) => {
    const input = el as HTMLInputElement;
    input.value = String(value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, target);

  await expect(frame.getByText("乙章開場").first()).toBeVisible({
    timeout: 15_000,
  });

  // Chapter ticks share the weight scale with the seek mapping: the
  // two-chapter fixture gets exactly one tick, sitting on the chapter 2
  // boundary the seek above just crossed.
  const ticks = page.locator("[data-scrubber-ticks] [data-tick]");
  await expect(ticks).toHaveCount(1);
  const tickPct = parseFloat((await ticks.first().getAttribute("data-tick"))!);
  expect(Math.abs(tickPct - (before / total) * 100)).toBeLessThan(0.5);
});
