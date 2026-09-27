import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/**
 * Searching the library switches the list to "Most relevant"; clearing
 * the search goes back to the order the user was browsing in.
 */

test.use({ storageState: ADMIN_STATE });

function nextListSort(page: Page) {
  return page
    .waitForRequest((r) => /\/api\/books\/(all|feed)\?/.test(r.url()))
    .then((r) => new URL(r.url()).searchParams.get("sort"));
}

test("search sorts by relevance, clearing restores the browse order", async ({
  page,
}) => {
  await page.goto("/libraries/all");
  const sort = page.locator("[data-select-trigger]").first();
  await expect(sort).toHaveText(/Newest added/);

  // Browse by title first, so "restored" can't be the default by luck.
  let sent = nextListSort(page);
  await sort.click();
  await page.getByRole("option", { name: "Title A → Z" }).click();
  expect(await sent).toBe("display_title");

  const search = page.getByPlaceholder(/Search/);
  sent = nextListSort(page);
  await search.fill("E2E");
  expect(await sent).toBe("relevance");
  await expect(sort).toHaveText(/Most relevant/);

  sent = nextListSort(page);
  await page.getByRole("button", { name: "Clear" }).click();
  expect(await sent).toBe("display_title");
  await expect(sort).toHaveText(/Title A → Z/);

  // With no query, relevance isn't on the menu.
  await sort.click();
  await expect(page.getByRole("option", { name: "Most relevant" })).toHaveCount(
    0,
  );
});
