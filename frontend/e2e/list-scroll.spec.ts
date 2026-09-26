import { test, expect } from "@playwright/test";
import { ADMIN_STATE, LIBRARY_NAME } from "./helpers";

/**
 * Back from a book lands where the list was left. The list pages fetch
 * after mount; without a snapshot the scroll restore hit the skeleton and
 * clamped, dropping the reader somewhere else in the list.
 */

test.use({ storageState: ADMIN_STATE, viewport: { width: 420, height: 760 } });

test("back from a book returns to the same spot in a reading list", async ({
  page,
}) => {
  const libraries = await (await page.request.get("/api/libraries")).json();
  const library = libraries.find(
    (l: { name: string }) => l.name === LIBRARY_NAME,
  );
  const all = await (
    await page.request.get(`/api/libraries/${library.id}/books?limit=100`)
  ).json();
  // The "read" shelf, filled with the fixture library (the list itself is
  // the page under test, not the status bookkeeping behind it).
  const items = all.items
    .filter((b: { file_size: number | null }) => b.file_size !== null)
    .map((b: Record<string, unknown>) => ({
      ...b,
      reading_status: "read",
      is_favorite: false,
      user_rating: null,
    }));
  expect(items.length).toBeGreaterThan(8);
  await page.route(/\/api\/books\/me\?/, (route) =>
    route.fulfill({ json: { items, total: items.length } }),
  );

  await page.goto("/my-books?tab=read");
  const cards = page.locator("main h3");
  await expect(cards.first()).toBeVisible();
  const target = cards.nth(items.length - 2);
  await target.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => window.scrollY);
  expect(before).toBeGreaterThan(300);

  await target.click();
  await expect(page).toHaveURL(/\/books\/[0-9a-f-]+$/);
  await page.getByRole("link", { name: "Back" }).first().click();
  await expect(page).toHaveURL(/\/my-books\?tab=read$/);
  await expect
    .poll(() => page.evaluate(() => window.scrollY))
    .toBeGreaterThan(before - 5);
  expect(await page.evaluate(() => window.scrollY)).toBeLessThan(before + 5);
});
