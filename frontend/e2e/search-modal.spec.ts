import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/** Open the global search (⌘K) and return its input. The shortcut only
 *  works once the page has hydrated, which the first load after a stack
 *  rebuild can take a moment to do: keep pressing until the modal
 *  answers. */
async function openSearch(page: Page) {
  const input = page.getByRole("dialog").getByRole("textbox");
  await expect(async () => {
    await page.keyboard.press("ControlOrMeta+k");
    await expect(input).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
  return input;
}

/** The modal's own request: the library list's endpoint, asked for a
 *  query's first twenty. (The list pages ask the same endpoint for
 *  sixty, and the home page for none with a search.) */
function isModalSearch(url: string | URL) {
  const u = new URL(url);
  return (
    u.pathname === "/api/books/all" &&
    u.searchParams.has("search") &&
    u.searchParams.get("limit") === "20"
  );
}
const bookPage = /\/books\/[0-9a-f-]{36}/;

/**
 * Regression for the global-search empty-state flash: debounced typing
 * keeps several book-search requests in flight, and an older
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
  await page.route(isModalSearch, async (route) => {
    call += 1;
    if (call === 1) {
      await new Promise((r) => setTimeout(r, 1500));
      // (The modal has given this request up by now; answering it is
      // answering nobody.)
      await route
        .fulfill({
          contentType: "application/json",
          body: JSON.stringify({ items: [], total: 0 }),
        })
        .catch(() => {});
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  const input = await openSearch(page);

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
  const firstRequest = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2");
  await firstRequest;
  // … then type on so request 2 (fast, with results) races past it.
  // A query only the test book matches: the search ranks prefix matches
  // shorter-title-first, and the fixtures other specs upload every run
  // (the shorter "E2E 直排標點測試") pile up in this persistent database
  // until they fill the 20-result page on a bare "E2E".
  await input.fill("E2E Test");

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

/**
 * Enter submits the search; it does not pick a result. It used to open
 * the first book — at once if the results were in, or whenever a slow
 * response landed — so pressing Enter after typing threw the user into a
 * book they had not chosen. Now, with nothing selected, Enter on the
 * Books tab goes to the library's own search (all libraries) with the
 * query; on the passage tabs it runs the search and leaves the results
 * up. A result is opened only when it was picked.
 */

test("Enter with results on screen goes to the library search, not into the first book", async ({
  page,
}) => {
  await page.goto("/");
  const input = await openSearch(page);
  await input.fill("E2E Test");
  const first = page.getByRole("dialog").getByText("E2E Test Book").first();
  await expect(first).toBeVisible({ timeout: 10_000 });

  await input.press("Enter");
  await expect(page).toHaveURL(/\/libraries\/all\?search=E2E(%20|\+)Test$/);
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByPlaceholder("Search all libraries...")).toHaveValue(
    "E2E Test",
  );
  await expect(page.getByText("E2E Test Book").first()).toBeVisible();
  await page.waitForTimeout(1000);
  expect(page.url()).not.toMatch(bookPage);
});

test("Enter before a slow search answers does not open a book when the answer lands", async ({
  page,
}) => {
  const visited: string[] = [];
  page.on("framenavigated", (f) => {
    if (f === page.mainFrame()) visited.push(f.url());
  });
  await page.route(isModalSearch, async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue().catch(() => {});
  });
  await page.goto("/");
  const input = await openSearch(page);
  const asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2E Test");
  await asked;
  await input.press("Enter");
  await expect(page).toHaveURL(/\/libraries\/all\?search=/);
  // Well past the slow answer.
  await page.waitForTimeout(2500);
  await expect(page).toHaveURL(/\/libraries\/all\?search=/);
  expect(visited.filter((u) => bookPage.test(u))).toEqual([]);
  await expect(page.getByPlaceholder("Search all libraries...")).toHaveValue(
    "E2E Test",
  );
});

test("from the library itself, Enter searches that list; Back returns to it as it was", async ({
  page,
}) => {
  await page.goto("/libraries/all");
  const search = page.getByPlaceholder("Search all libraries...");
  await expect(search).toHaveValue("");
  const input = await openSearch(page);
  await input.fill("E2E Test");
  const listed = page.waitForRequest(
    (r) =>
      /\/api\/books\/(all|feed)\?/.test(r.url()) &&
      // (The list's request, not the modal's for the same words.)
      !isModalSearch(r.url()) &&
      new URL(r.url()).searchParams.get("search") === "E2E Test",
  );
  await input.press("Enter");
  await listed;
  await expect(page).toHaveURL(/\/libraries\/all\?search=/);
  await expect(search).toHaveValue("E2E Test");
  await expect(page.getByText("E2E Test Book").first()).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/libraries\/all$/);
  await expect(search).toHaveValue("");
});

test("a result picked with the arrow keys is opened by Enter", async ({
  page,
}) => {
  await page.goto("/");
  const input = await openSearch(page);
  await input.fill("E2E Test");
  await expect(
    page.getByRole("dialog").getByText("E2E Test Book").first(),
  ).toBeVisible({ timeout: 10_000 });
  await input.press("ArrowDown");
  await input.press("Enter");
  await expect(page).toHaveURL(bookPage);
});

test("typing on aborts the search it has made pointless", async ({ page }) => {
  // Every search is slow: the first is still out when the second key
  // comes.
  await page.route(isModalSearch, async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue().catch(() => {});
  });
  const aborted: string[] = [];
  page.on("requestfailed", (r) => {
    if (isModalSearch(r.url()))
      aborted.push(
        `${new URL(r.url()).searchParams.get("search")}: ${r.failure()?.errorText}`,
      );
  });
  await page.goto("/");
  const input = await openSearch(page);
  let asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2");
  await asked;
  asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2E Test");
  await expect.poll(() => aborted).toEqual(["E2: net::ERR_ABORTED"]);
  await asked;
  // The one that is wanted is answered …
  await expect(
    page.getByRole("dialog").getByText("E2E Test Book").first(),
  ).toBeVisible({ timeout: 10_000 });
  // … and closing the modal gives up what it is still waiting for.
  asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2E Te");
  await asked;
  await page.keyboard.press("Escape");
  await expect
    .poll(() => aborted)
    .toEqual(["E2: net::ERR_ABORTED", "E2E Te: net::ERR_ABORTED"]);
  // An abandoned request is not a lost connection: no error is shown.
  await expect(page.locator(".toast-position [role=status]")).toHaveCount(0);
});

test("on the passage tabs Enter runs the search and leaves the results up", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/search/keyword*", async (route) => {
    calls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        query: "lantern",
        total: 1,
        results: [
          {
            book_id: "00000000-0000-4000-8000-000000000001",
            book_title: "The Lantern Ledger",
            book_author: "A. Keeper",
            passage: "The lantern was lit at dusk.",
            spine_index: 0,
            char_offset_start: 0,
            char_offset_end: 28,
          },
        ],
      }),
    });
  });
  await page.goto("/");
  const start = page.url();
  const input = await openSearch(page);
  await page.getByRole("tab", { name: "Full Text" }).click();
  await input.fill("lantern");
  // Typing alone does not search here.
  await page.waitForTimeout(600);
  expect(calls).toBe(0);

  await input.press("Enter");
  const hit = page.getByRole("dialog").getByText("The Lantern Ledger");
  await expect(hit).toBeVisible();
  expect(calls).toBe(1);
  // Enter again: the results are already there; nothing is opened and
  // nothing is asked twice.
  await input.press("Enter");
  await page.waitForTimeout(600);
  await expect(hit).toBeVisible();
  expect(calls).toBe(1);
  expect(page.url()).toBe(start);
});

/**
 * The modal and the library list ask one endpoint, so what the modal
 * shows is the head of the list Enter leads to: the same books, in the
 * same order.
 */
test("the modal lists the first books of the library search, in its order", async ({
  page,
}) => {
  await page.goto("/");
  for (const q of ["E2E", "E2E Test", "test", "書"]) {
    const input = await openSearch(page);
    const answered = page.waitForResponse(
      (r) =>
        isModalSearch(r.url()) &&
        new URL(r.url()).searchParams.get("search") === q,
    );
    await input.fill(q);
    const answer = await (await answered).json();
    expect(answer.items.length, q).toBeGreaterThan(0);
    const rows = page.getByRole("dialog").locator("[role=tabpanel] > button");
    await expect(rows, q).toHaveCount(answer.items.length);
    const modalTitles = await rows.evaluateAll((els) =>
      els.map((el) => el.querySelector("p")?.textContent?.trim()),
    );

    const listed = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/books/all" &&
        !isModalSearch(r.url()) &&
        new URL(r.url()).searchParams.get("search") === q,
    );
    await input.press("Enter");
    const list = await (await listed).json();
    await expect(page).toHaveURL(/\/libraries\/all\?search=/);
    const cards = page.locator(".book-grid > [role=button]");
    await expect(cards, q).toHaveCount(list.items.length);
    const listTitles = await cards.evaluateAll((els) =>
      els.map((el) => el.querySelector("h3")?.textContent?.trim()),
    );
    // On screen: the same titles, in the same order …
    expect(listTitles.slice(0, modalTitles.length), q).toEqual(modalTitles);
    // … and they are the same books, not namesakes.
    expect(
      list.items.slice(0, answer.items.length).map((b: { id: string }) => b.id),
      q,
    ).toEqual(answer.items.map((b: { id: string }) => b.id));
    expect(list.total, q).toBe(answer.total);
  }
});
