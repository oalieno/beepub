import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/**
 * Regression for the global-search empty-state flash: debounced typing
 * keeps several /api/books/search requests in flight, and an older
 * response finishing while a newer request still ran used to clear
 * `loading` — the modal read "not loading + no results" and flashed
 * "No books found" before the real results arrived. Stale responses may
 * touch neither the results nor the loading flag.
 */

test.use({ storageState: ADMIN_STATE });

test("a stale search response cannot flash the empty state", async ({
  page,
}) => {
  // First search request ("E2"): delayed and empty. Second ("E2E"):
  // fast, with results. The old race: the slow empty response lands
  // after the fast one started, clears loading, and the empty state
  // flashes until the fast response arrives.
  let call = 0;
  await page.route("**/api/books/search*", async (route) => {
    call += 1;
    if (call === 1) {
      await new Promise((r) => setTimeout(r, 1500));
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  await page.keyboard.press("ControlOrMeta+k");
  const input = page.getByRole("textbox");
  await expect(input).toBeVisible();

  // Watch for any appearance of the empty state inside the modal's
  // results panel from now on (the string also exists in page content
  // behind the modal, so scope tightly).
  await page.evaluate(() => {
    const w = window as unknown as { __sawEmpty: boolean };
    w.__sawEmpty = false;
    new MutationObserver(() => {
      const panel = document.querySelector('[role="tabpanel"]');
      if (panel?.textContent?.includes("No books found")) {
        w.__sawEmpty = true;
      }
    }).observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  });

  // The race needs request 1 (slow, empty) actually IN FLIGHT before the
  // second keystroke — a fixed debounce sleep loses under load (both
  // keystrokes coalesce into one request, which meets the slow stub and
  // the results never arrive; flaked right after e2e image rebuilds).
  const firstRequest = page.waitForRequest((r) =>
    r.url().includes("/api/books/search"),
  );
  await input.fill("E2");
  await firstRequest;
  // … then type on so request 2 (fast, with results) races past it.
  await input.fill("E2E");

  // The fast response's results appear …
  await expect(
    page.getByText("E2E Test Book", { exact: false }).first(),
  ).toBeVisible({ timeout: 10_000 });
  // … and stay after the stale response lands.
  await page.waitForTimeout(1500);
  await expect(
    page.getByText("E2E Test Book", { exact: false }).first(),
  ).toBeVisible();

  const sawEmpty = await page.evaluate(
    () => (window as unknown as { __sawEmpty: boolean }).__sawEmpty,
  );
  expect(sawEmpty).toBe(false);
});
